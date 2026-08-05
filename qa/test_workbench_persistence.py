"""
工作面板待办 / 随心记 后端持久化 —— 真实 HTTP 集成测试 (QA 独立验证)

运行：
    /Users/graypaul/.workbuddy/binaries/python/envs/default/bin/python -m pytest qa/test_workbench_persistence.py -v

说明：
- 通过 monkeypatch backend.database.Database.__init__，把全局 db 单例重定向到
  全新临时 SQLite 文件，避免污染真实 data/app.db。
- 使用 fastapi.testclient.TestClient 发起真实 HTTP 请求，经完整装配（路由 + Pydantic
  请求/响应序列化）验证契约。
- 每个用例前清空 workbench 两张表，保证用例间隔离。

契约要点（来自 docs/workbench_persistence_design.md §1.2 / §2.2）：
- 请求与响应均为 camelCase；DB 列 snake_case；转换由 Pydantic 边界完成（field name
  snake_case + alias camelCase + populate_by_name）。
- TaskOut 响应字段（camelCase）：id, userKey, title, notes, priority, dueDate, dueTime,
  reminderAt, completed, notifiedAt, createdAt, updatedAt
- NoteOut 响应字段（camelCase）：id, userKey, content, createdAt, updatedAt
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

# ---------------- 隔离测试库：导入 backend.main 之前重定向 Database ----------------
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_TMP_DIR = tempfile.mkdtemp(prefix="wb_qa_")
_TMP_DB = os.path.join(_TMP_DIR, "test_app.db")

import backend.database as _bd

_orig_db_init = _bd.Database.__init__


def _patched_db_init(self, db_path=None):
    # 无视传入路径，统一落入临时文件，避免触碰真实 data/app.db
    _orig_db_init(self, Path(_TMP_DB))


_bd.Database.__init__ = _patched_db_init

import backend.main as main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

# 契约规定的 camelCase 响应字段
TASK_OUT_KEYS = [
    "id", "userKey", "title", "notes", "priority", "dueDate",
    "dueTime", "reminderAt", "completed", "notifiedAt", "createdAt", "updatedAt",
]
NOTE_OUT_KEYS = ["id", "userKey", "content", "createdAt", "updatedAt"]


@pytest.fixture
def api():
    # 每个用例前清空工作面板表（不影响真实库，仅清空临时库）
    with main.db.connect() as conn:
        conn.execute("DELETE FROM workbench_tasks")
        conn.execute("DELETE FROM workbench_notes")
    with TestClient(main.app) as c:
        yield c


# ---------------- 用例 ----------------
def test_tables_exist(api):
    """用例1：启动后两张表 workbench_tasks / workbench_notes 存在。"""
    with main.db.connect() as conn:
        names = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "workbench_tasks" in names
    assert "workbench_notes" in names


def test_task_camel_case_roundtrip(api):
    """用例2：POST camelCase 入参 -> GET 返回一致且字段为 camelCase。

    同时验证 camelCase 入参（dueTime / reminderAt / createdAt ...）被正确接受并落库，
    这是“前端零映射”契约的核心。
    """
    payload = {
        "id": "t-001",
        "title": "示例待办",
        "notes": "补充说明",
        "priority": "high",
        "dueDate": "2026-08-10",
        "dueTime": "09:30",
        "reminderAt": "2026-08-10T09:00:00",
        "completed": False,
        "notifiedAt": "",
        "createdAt": "2026-08-05T08:00:00.000Z",
        "updatedAt": "2026-08-05T08:00:00.000Z",
    }
    r = api.post("/api/workbench/tasks", params={"user_key": "UK_A"}, json=payload)
    assert r.status_code == 200, r.text
    body = r.json()

    # 响应必须是完整的 camelCase 字段
    missing = [k for k in TASK_OUT_KEYS if k not in body]
    assert not missing, f"响应缺少 camelCase 字段 {missing}；实际字段={list(body.keys())}"

    # 值应一致（证明 camelCase 入参被正确接受并持久化）
    assert body["dueTime"] == "09:30", body
    assert body["reminderAt"] == "2026-08-10T09:00:00", body
    assert body["createdAt"] == "2026-08-05T08:00:00.000Z", body

    # GET 回来也应一致
    g = api.get("/api/workbench/tasks", params={"user_key": "UK_A"})
    assert g.status_code == 200, g.text
    items = g.json()["items"]
    assert len(items) == 1, items
    assert items[0]["dueTime"] == "09:30", items[0]
    assert items[0]["reminderAt"] == "2026-08-10T09:00:00", items[0]


def test_user_key_isolation(api):
    """用例3：user_key 隔离，UK_A 与 UK_B 数据互不可见，default 也看不到。"""
    api.post("/api/workbench/tasks", params={"user_key": "UK_A"}, json={"title": "A任务"})
    api.post("/api/workbench/tasks", params={"user_key": "UK_B"}, json={"title": "B任务"})

    a = api.get("/api/workbench/tasks", params={"user_key": "UK_A"}).json()["items"]
    b = api.get("/api/workbench/tasks", params={"user_key": "UK_B"}).json()["items"]
    assert [t["title"] for t in a] == ["A任务"], a
    assert [t["title"] for t in b] == ["B任务"], b

    # 缺省 user_key='default' 看不到 A/B 的数据
    d = api.get("/api/workbench/tasks").json()["items"]
    assert len(d) == 0, d


def test_task_update_partial_and_404(api):
    """用例4：PUT 部分更新 completed=true，其余字段保留；不存在 id -> 404。"""
    created = api.post(
        "/api/workbench/tasks", params={"user_key": "UK_A"},
        json={"title": "待办", "priority": "low"},
    ).json()
    tid = created["id"]

    r = api.put(f"/api/workbench/tasks/{tid}", params={"user_key": "UK_A"},
                json={"completed": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["completed"] is True
    assert body["title"] == "待办"          # 其余字段应保留
    assert body["priority"] == "low"

    r404 = api.put("/api/workbench/tasks/nope", params={"user_key": "UK_A"},
                   json={"completed": True})
    assert r404.status_code == 404, r404.text


def test_task_delete_204_and_404(api):
    """用例5：DELETE -> 204；再次 DELETE -> 404。"""
    created = api.post(
        "/api/workbench/tasks", params={"user_key": "UK_A"}, json={"title": "待删"}
    ).json()
    tid = created["id"]

    r = api.delete(f"/api/workbench/tasks/{tid}", params={"user_key": "UK_A"})
    assert r.status_code == 204, r.text
    r2 = api.delete(f"/api/workbench/tasks/{tid}", params={"user_key": "UK_A"})
    assert r2.status_code == 404, r2.text


def test_notes_camel_case_output(api):
    """用例6（契约）：笔记响应必须为 camelCase 字段（userKey/createdAt/updatedAt）。"""
    r = api.post(
        "/api/workbench/notes", params={"user_key": "UK_A"},
        json={"id": "n-1", "content": "hello",
              "createdAt": "2026-08-05T08:00:00.000Z",
              "updatedAt": "2026-08-05T08:00:00.000Z"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    missing = [k for k in NOTE_OUT_KEYS if k not in body]
    assert not missing, f"笔记响应缺少 camelCase 字段 {missing}；实际字段={list(body.keys())}"
    assert body["createdAt"] == "2026-08-05T08:00:00.000Z", body


def test_notes_crud(api):
    """用例6（全链路）：笔记 CRUD + 不存在 id -> 404。"""
    c = api.post("/api/workbench/notes", params={"user_key": "UK_A"},
                 json={"content": "第一笔"}).json()
    nid = c["id"]
    assert c["content"] == "第一笔"

    u = api.put(f"/api/workbench/notes/{nid}", params={"user_key": "UK_A"},
                json={"content": "改后"}).json()
    assert u["content"] == "改后"

    lst = api.get("/api/workbench/notes", params={"user_key": "UK_A"}).json()["items"]
    assert len(lst) == 1 and lst[0]["content"] == "改后", lst

    d = api.delete(f"/api/workbench/notes/{nid}", params={"user_key": "UK_A"})
    assert d.status_code == 204, d.text
    d2 = api.delete(f"/api/workbench/notes/{nid}", params={"user_key": "UK_A"})
    assert d2.status_code == 404, d2.text
    assert api.put(f"/api/workbench/notes/nope", params={"user_key": "UK_A"},
                   json={"content": "x"}).status_code == 404


def test_note_content_too_long_400(api):
    """用例6（边界）：content 501 字 -> 400。"""
    r = api.post("/api/workbench/notes", params={"user_key": "UK_A"},
                 json={"content": "x" * 501})
    assert r.status_code == 400, r.text
    assert "detail" in r.json()


def test_title_too_long_400(api):
    """用例7：title 81 字 -> 400。"""
    r = api.post("/api/workbench/tasks", params={"user_key": "UK_A"},
                 json={"title": "x" * 81})
    assert r.status_code == 400, r.text
    assert "detail" in r.json()


def test_migrate_idempotent(api):
    """用例8：POST /migrate 重复两次（同一批）-> 表中行数各为 1（幂等），
    响应 migrated_tasks / migrated_notes 正确。"""
    batch = {
        "user_key": "UK_A",
        "tasks": [{"id": "m-t1", "title": "迁移任务", "dueDate": "2026-08-20",
                   "priority": "medium"}],
        "notes": [{"id": "m-n1", "content": "迁移笔记"}],
    }
    r1 = api.post("/api/workbench/migrate", json=batch)
    assert r1.status_code == 200, r1.text
    assert r1.json()["migrated_tasks"] == 1, r1.text
    assert r1.json()["migrated_notes"] == 1, r1.text

    r2 = api.post("/api/workbench/migrate", json=batch)
    assert r2.status_code == 200, r2.text
    assert r2.json()["migrated_tasks"] == 1, r2.text
    assert r2.json()["migrated_notes"] == 1, r2.text

    with main.db.connect() as conn:
        tcount = conn.execute(
            "SELECT COUNT(*) AS c FROM workbench_tasks WHERE user_key='UK_A'").fetchone()["c"]
        ncount = conn.execute(
            "SELECT COUNT(*) AS c FROM workbench_notes WHERE user_key='UK_A'").fetchone()["c"]
    assert tcount == 1, tcount
    assert ncount == 1, ncount


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
