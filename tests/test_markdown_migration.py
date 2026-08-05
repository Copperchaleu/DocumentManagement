"""T05 后端验证：Markdown 迁移的往返校验、幂等、备份/回滚、双写、Word BLOB 保留、依赖锁定。

覆盖 P0-1 / P0-2 / P0-3 / P0-4 / P0-5 / P0-6 / P0-12（后端部分）。

安全约定：
- 所有写库操作只在临时 SQLite 上执行（pytest tmp_path）。
- 通过 monkeypatch 把迁移/报告脚本的 ``ROOT_DIR`` 重定向到临时目录，
  避免向仓库 ``docs/`` 写入 validation.json / migration_impact_report.json。
- 绝不针对生产库 ``data/app.db`` 执行真实迁移（--no-dry-run）。
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from backend.database import Database  # noqa: E402
from backend.markdown_utils import (  # noqa: E402
    get_plain_text,
    html_to_md,
    md_to_plain_text,
    sniff_content_format,
)
from backend.word_service import html_to_plain_text  # noqa: E402
import migrate_html_to_md  # noqa: E402
import migration_impact_report  # noqa: E402
import rollback_html_from_md  # noqa: E402


# ---------------------------------------------------------------------------
# 测试样本：≥8 条 wangEditor HTML，覆盖标题/粗体/斜体/删除线/有序无序列表/
# 引用/链接/嵌套列表，以及纯展示样式（font/size/color/align/span style）。
# ---------------------------------------------------------------------------
SAMPLE_HTML: list[str] = [
    # 1. 标题
    "<h1>一季度经营总结</h1>",
    # 2. 粗体 + 斜体
    "<p>这是<strong>重点内容</strong>与<em>强调说明</em>。</p>",
    # 3. 删除线（wangEditor 用 <s> 标签）
    "<p>原计划<s>已取消</s>的项目安排。</p>",
    # 4. 有序列表
    "<ol><li>第一步准备材料</li><li>第二步提交审批</li><li>第三步归档留存</li></ol>",
    # 5. 无序列表
    "<ul><li>苹果</li><li>香蕉</li><li>橙子</li></ul>",
    # 6. 嵌套列表
    (
        "<ul><li>水果"
        "<ul><li>苹果</li><li>香蕉</li></ul>"
        "</li><li>蔬菜</li></ul>"
    ),
    # 7. 引用
    "<blockquote>客户要求本周内交付初稿，逾期将影响验收。</blockquote>",
    # 8. 链接
    '<p>详见规范文档<a href="https://example.com/spec">点击查看</a>。</p>',
    # 9. 纯展示样式（font/size/color/align/span style）
    (
        '<p style="text-align: center;">'
        '<span style="color: rgb(255, 0, 0); font-size: 20px; '
        'font-family: 微软雅黑;">红色标题文字</span></p>'
    ),
    # 10. 综合多块
    (
        "<h2>章节二</h2>"
        "<p>正文段落，含<strong>粗体</strong>与<em>斜体</em>。</p>"
        "<blockquote>重要提示</blockquote>"
        "<ul><li>要点一</li><li>要点二</li></ul>"
    ),
]


def _roundtrip(html: str):
    """返回 (diff_count, original_plain, md_plain)。"""
    md = html_to_md(html)
    original_plain = html_to_plain_text(html)
    md_plain = md_to_plain_text(md)
    diff_count = migrate_html_to_md.validate_roundtrip(html, md)
    return diff_count, original_plain, md_plain


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def redirect_script_reports(tmp_path, monkeypatch):
    """把迁移/影响报告脚本的 ROOT_DIR 重定向到临时目录，避免污染仓库 docs/。"""
    monkeypatch.setattr(migrate_html_to_md, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(migration_impact_report, "ROOT_DIR", tmp_path)


@pytest.fixture
def seeded_db(tmp_path, redirect_script_reports):
    """构建一个含 10 条 html 真源项目 + 历史 Word BLOB 的临时库。"""
    db_path = tmp_path / "app.db"
    db = Database(db_path)
    cat = db.create_category(name="测试分类")
    cid = int(cat["id"])

    pids: list[int] = []
    for i, html in enumerate(SAMPLE_HTML):
        proj = db.create_project(
            title=f"项目{i}",
            category_id=cid,
            content=html,
            content_preview="",
            time_modes=["month"],
            week_label=None,
            month_label="2026-08",
            quarter_label=None,
            content_format="html",
        )
        pids.append(int(proj["id"]))

    # 注入历史 Word BLOB：一个 period_file + 2 个版本（migration/rollback 不得改写）。
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO period_files (
                category_id, period_type, period_label, relative_path,
                word_filename, project_count, local_sync_status, last_sync_error, updated_at
            ) VALUES (?, 'month', '2026-08', 'rel/path.docx', 'w.docx', 10, 'synced', '', '2026-08-01 00:00:00')
            """,
            (cid,),
        )
        pfid = conn.execute(
            "SELECT id FROM period_files WHERE category_id=? AND period_type='month' AND period_label='2026-08'",
            (cid,),
        ).fetchone()["id"]
        blob_a = b"\x50\x4b\x03\x04 FAKE_DOCX_VERSION_A" + bytes(range(256))
        blob_b = b"\x50\x4b\x03\x04 FAKE_DOCX_VERSION_B" + bytes(reversed(range(256)))
        conn.execute(
            """
            INSERT INTO period_file_versions (
                period_file_id, version_no, file_content, file_size,
                file_sha256, source_sha256, project_count, change_reason, created_at
            ) VALUES (?, 1, ?, ?, 'shaA', 'srcA', 10, '初版', '2026-08-01 00:00:00')
            """,
            (pfid, sqlite3.Binary(blob_a), len(blob_a)),
        )
        conn.execute(
            """
            INSERT INTO period_file_versions (
                period_file_id, version_no, file_content, file_size,
                file_sha256, source_sha256, project_count, change_reason, created_at
            ) VALUES (?, 2, ?, ?, 'shaB', 'srcB', 10, '修订', '2026-08-02 00:00:00')
            """,
            (pfid, sqlite3.Binary(blob_b), len(blob_b)),
        )

    return {
        "db": db,
        "db_path": db_path,
        "category_id": cid,
        "project_ids": pids,
        "period_file_id": pfid,
        "blob_a": blob_a,
        "blob_b": blob_b,
    }


# ---------------------------------------------------------------------------
# P0-2 双写过渡列 + 格式嗅探 + 旧库 ALTER
# ---------------------------------------------------------------------------
def test_sniff_content_format():
    assert sniff_content_format("<p>hello</p>") == "html"
    assert sniff_content_format("<h1>标题</h1>") == "html"
    assert sniff_content_format("# 这是 Markdown") == "md"
    assert sniff_content_format("纯文本段落内容") == "md"
    assert sniff_content_format("") == "md"


def test_get_plain_text_dispatch():
    html = "<p>甲<strong>乙</strong></p>"
    md = "# 标题\n\n正文"
    assert get_plain_text(html, "html") == html_to_plain_text(html)
    assert get_plain_text(md, "md") == md_to_plain_text(md)
    # 未知 format 按 html 处理
    assert get_plain_text(html, "unknown") == html_to_plain_text(html)


def test_new_db_has_migration_columns_with_default_html(tmp_path, redirect_script_reports):
    db_path = tmp_path / "fresh.db"
    db = Database(db_path)
    with db.connect() as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(projects)").fetchall()}
        assert "content_format" in cols
        assert "content_html_backup" in cols
        # 默认约束
        info = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='projects'"
        ).fetchone()["sql"]
        assert "content_format" in info
        # 模拟 save_project：后端嗅探 format 后按 format 持久化（P0-2 双写）
        cat = db.create_category(name="C")
        cid = int(cat["id"])
        # 新内容（无 HTML）→ 嗅探为 md
        md_content = "# Markdown 内容\n\n正文"
        proj = db.create_project(
            title="T", category_id=cid, content=md_content,
            content_preview="", time_modes=["month"],
            week_label=None, month_label=None, quarter_label=None,
            content_format=sniff_content_format(md_content),
        )
        assert proj["content_format"] == "md"
        # 含 HTML 内容 → 嗅探为 html
        html_content = "<p>HTML 内容</p>"
        proj2 = db.create_project(
            title="T2", category_id=cid, content=html_content,
            content_preview="", time_modes=["month"],
            week_label=None, month_label=None, quarter_label=None,
            content_format=sniff_content_format(html_content),
        )
        assert proj2["content_format"] == "html"
        # 不传 format（缺省）→ 落库为默认 'html'
        proj3 = db.create_project(
            title="T3", category_id=cid, content="纯文本",
            content_preview="", time_modes=["month"],
            week_label=None, month_label=None, quarter_label=None,
        )
        assert proj3["content_format"] == "html"


def test_old_db_alter_adds_columns_without_data_loss(tmp_path, redirect_script_reports):
    """模拟旧库（projects 缺 content_format/content_html_backup），经 Database 初始化
    后应自动加列、不报错、不丢数据，且历史行 content_format 落为默认 'html'。"""
    old_db = tmp_path / "old.db"
    conn = sqlite3.connect(old_db)
    conn.executescript(
        """
        CREATE TABLE categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT, parent_id INTEGER, name TEXT NOT NULL,
            path TEXT DEFAULT '', description TEXT DEFAULT '', sort_order INTEGER DEFAULT 0,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, category_id INTEGER NOT NULL,
            content TEXT NOT NULL, content_preview TEXT DEFAULT '', time_modes_json TEXT NOT NULL DEFAULT '[]',
            week_label TEXT, month_label TEXT, quarter_label TEXT, status TEXT NOT NULL DEFAULT 'saved',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        "INSERT INTO categories (parent_id,name,path,description,sort_order,created_at,updated_at) "
        "VALUES (NULL,'旧分类','','',0,'2026-01-01 00:00:00','2026-01-01 00:00:00')"
    )
    old_content = "<p>旧内容<strong>粗体</strong></p>"
    conn.execute(
        "INSERT INTO projects (title,category_id,content,content_preview,time_modes_json,"
        "week_label,month_label,quarter_label,status,created_at,updated_at) "
        "VALUES ('旧项目',1,?, '','[]',NULL,'2026-01',NULL,'saved','2026-01-01 00:00:00','2026-01-01 00:00:00')",
        (old_content,),
    )
    conn.commit()
    conn.close()

    # 触发迁移（含 _ensure_migration_columns）
    db = Database(old_db)
    with db.connect() as c:
        cols = {r["name"] for r in c.execute("PRAGMA table_info(projects)").fetchall()}
        assert "content_format" in cols
        assert "content_html_backup" in cols
        row = c.execute("SELECT content, content_format FROM projects WHERE id=1").fetchone()
        assert row["content"] == old_content  # 数据未丢
        assert row["content_format"] == "html"  # 缺省被归一为 html


# ---------------------------------------------------------------------------
# P0-3 / P0-4 幂等迁移 + 往返校验 100%
# ---------------------------------------------------------------------------
def test_roundtrip_unit_samples():
    """单元级：每条样本的 md→纯文本 必须等于 原 html→纯文本（diff=0）。"""
    for i, html in enumerate(SAMPLE_HTML):
        diff, orig, mdplain = _roundtrip(html)
        assert diff == 0, f"样本#{i} 往返 diff_count={diff}\norig={orig!r}\nmd={mdplain!r}"
        assert orig == mdplain, f"样本#{i} 纯文本不一致:\norig={orig!r}\nmd={mdplain!r}"


def test_migrate_dry_run_only_counts(seeded_db, redirect_script_reports):
    """dry-run 不写库：content_format 保持 html，但能统计通过率。"""
    db_path = seeded_db["db_path"]
    summary = migrate_html_to_md.run(db_path, dry_run=True)
    assert summary["total"] == len(SAMPLE_HTML)
    assert summary["roundtrip_failed"] == 0
    assert summary["pass_rate"] == 1.0
    assert summary["written"] == 0
    # 未写库，仍是 html
    with seeded_db["db"].connect() as conn:
        fmts = [r["content_format"] for r in conn.execute("SELECT content_format FROM projects")]
        assert all(f == "html" for f in fmts)


def test_migrate_real_writes_md_and_backup(seeded_db, redirect_script_reports):
    """真实迁移：content→md，content_format='md'，content_html_backup=原 html（逐字节）。"""
    db = seeded_db["db"]
    db_path = seeded_db["db_path"]
    summary = migrate_html_to_md.run(db_path, dry_run=False)
    assert summary["total"] == len(SAMPLE_HTML)
    assert summary["roundtrip_failed"] == 0
    assert summary["pass_rate"] == 1.0
    assert summary["written"] == len(SAMPLE_HTML)

    with db.connect() as conn:
        rows = conn.execute(
            "SELECT id, content, content_format, content_html_backup FROM projects ORDER BY id"
        ).fetchall()
    for idx, row in enumerate(rows):
        assert row["content_format"] == "md"
        # 备份逐字节等于原始 HTML
        assert row["content_html_backup"] == SAMPLE_HTML[idx]
        # 迁移后的 md 经 md_to_plain_text 与原始 html 纯文本一致
        assert md_to_plain_text(row["content"]) == html_to_plain_text(SAMPLE_HTML[idx])


def test_migrate_idempotent_no_duplicate_write(seeded_db, redirect_script_reports):
    """重跑安全：已转 md 的行被跳过，不重复转换、不丢内容。"""
    db = seeded_db["db"]
    db_path = seeded_db["db_path"]
    migrate_html_to_md.run(db_path, dry_run=False)

    # 快照第一次结果
    with db.connect() as conn:
        before = {
            r["id"]: (r["content"], r["content_html_backup"], r["content_format"])
            for r in conn.execute(
                "SELECT id, content, content_html_backup, content_format FROM projects"
            )
        }

    # 重跑（real）
    summary2 = migrate_html_to_md.run(db_path, dry_run=False)
    assert summary2["total"] == 0  # 已无 html 行可处理
    assert summary2["written"] == 0

    with db.connect() as conn:
        after = {
            r["id"]: (r["content"], r["content_html_backup"], r["content_format"])
            for r in conn.execute(
                "SELECT id, content, content_html_backup, content_format FROM projects"
            )
        }
    assert before == after  # 内容完全一致，无重复写入/丢失


# ---------------------------------------------------------------------------
# P0-1 全量在线备份
# ---------------------------------------------------------------------------
def test_migrate_creates_backup(seeded_db, redirect_script_reports):
    db_path = seeded_db["db_path"]
    summary = migrate_html_to_md.run(db_path, dry_run=False)
    backup_path = Path(summary["backup_path"])
    assert backup_path.exists()
    # 备份是可读的 SQLite
    src = sqlite3.connect(str(backup_path))
    try:
        n = src.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        assert n == len(SAMPLE_HTML)
    finally:
        src.close()


# ---------------------------------------------------------------------------
# P0-5 备份可回滚（含 MD-only 新内容不被误伤）
# ---------------------------------------------------------------------------
def test_rollback_restores_html_source(seeded_db, redirect_script_reports):
    db = seeded_db["db"]
    db_path = seeded_db["db_path"]
    original = list(SAMPLE_HTML)

    migrate_html_to_md.run(db_path, dry_run=False)

    # 新增一条「MD-only」新内容（backup 为 NULL），回滚不应误伤。
    md_only = "# 全新 Markdown 内容\n\n这是迁移后才写的内容。"
    md_proj = db.create_project(
        title="MD-only", category_id=seeded_db["category_id"], content=md_only,
        content_preview="", time_modes=["month"],
        week_label=None, month_label=None, quarter_label=None,
        content_format="md", content_html_backup=None,
    )
    md_only_id = int(md_proj["id"])

    # 回滚（真实写库）
    rsummary = rollback_html_from_md.run(db_path, dry_run=False)
    # 仅回滚了原先 10 条（有 backup 的），MD-only 不在内
    assert rsummary["written"] == len(SAMPLE_HTML)

    with db.connect() as conn:
        rows = {
            r["id"]: (r["content"], r["content_format"], r["content_html_backup"])
            for r in conn.execute(
                "SELECT id, content, content_format, content_html_backup FROM projects"
            )
        }

    for idx, html in enumerate(original):
        rid = seeded_db["project_ids"][idx]
        content, fmt, backup = rows[rid]
        assert fmt == "html"
        assert content == html  # 逐字节恢复
        assert backup is None

    # MD-only 新内容未被误伤
    mcontent, mfmt, mbackup = rows[md_only_id]
    assert mfmt == "md"
    assert mcontent == md_only
    assert mbackup is None


def test_rollback_dry_run_only_counts(seeded_db, redirect_script_reports):
    db_path = seeded_db["db_path"]
    migrate_html_to_md.run(db_path, dry_run=False)
    rsummary = rollback_html_from_md.run(db_path, dry_run=True)
    assert rsummary["written"] == 0
    assert rsummary["total"] == len(SAMPLE_HTML)
    # 未写库，仍是 md
    with seeded_db["db"].connect() as conn:
        fmts = [r["content_format"] for r in conn.execute("SELECT content_format FROM projects")]
        assert all(f == "md" for f in fmts)


def test_rollback_reversible_loop(seeded_db, redirect_script_reports):
    """可逆闭环：迁移 → 回滚 → 再迁移，结果应与首次迁移一致。"""
    db_path = seeded_db["db_path"]
    migrate_html_to_md.run(db_path, dry_run=False)
    rollback_html_from_md.run(db_path, dry_run=False)
    summary = migrate_html_to_md.run(db_path, dry_run=False)
    assert summary["written"] == len(SAMPLE_HTML)
    assert summary["roundtrip_failed"] == 0


# ---------------------------------------------------------------------------
# P0-6 历史 Word 版本 BLOB 保留
# ---------------------------------------------------------------------------
@pytest.mark.skip(
    reason="docx 移除：P0-6 历史 Word BLOB 保留作废；按新范围（历史 docx→md 迁移）重验"
)
def test_period_file_versions_preserved_through_migration(seeded_db, redirect_script_reports):
    db = seeded_db["db"]
    db_path = seeded_db["db_path"]

    def snapshot():
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT version_no, file_content, file_sha256, source_sha256 "
                "FROM period_file_versions WHERE period_file_id=? ORDER BY version_no",
                (seeded_db["period_file_id"],),
            ).fetchall()
            return [(r["version_no"], bytes(r["file_content"]), r["file_sha256"], r["source_sha256"]) for r in rows]

    before = snapshot()
    assert len(before) == 2
    migrate_html_to_md.run(db_path, dry_run=False)
    rollback_html_from_md.run(db_path, dry_run=False)
    after = snapshot()
    assert after == before  # 条数、BLOB 字节、指纹完全一致


# ---------------------------------------------------------------------------
# P0-12 依赖锁定
# ---------------------------------------------------------------------------
def test_requirements_lock_markdown_deps():
    req = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "markdownify" in req
    assert "mistune" in req
    # 版本锁定（含 ==）
    assert re_search(r"markdownify==\d", req)
    assert re_search(r"mistune==\d", req)


def test_package_json_lock_frontend_deps():
    pkg = (ROOT / "web" / "package.json").read_text(encoding="utf-8")
    assert '"md-editor-v3"' in pkg
    assert '"markdown-it"' in pkg
    # 已移除 wangeditor
    assert "wangeditor" not in pkg.lower()


def re_search(pattern: str, text: str) -> bool:
    import re

    return re.search(pattern, text) is not None


# ---------------------------------------------------------------------------
# P0-4 对真实生产库副本做 dry-run 往返校验（不写库）
# ---------------------------------------------------------------------------
def test_roundtrip_on_production_copy_dry_run(redirect_script_reports):
    """复制生产库到临时目录（绝不触碰原库），dry-run 验证真实 wangEditor 数据往返。"""
    prod = ROOT / "data" / "app.db"
    if not prod.exists():
        pytest.skip("生产库不存在，跳过真实数据校验")
    copy = None
    # 用独立临时目录
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="md_prod_copy_"))
    try:
        dst = tmp / "app.db"
        shutil.copy(prod, dst)
        # 记录迁移前 content_format；dry-run 必须零变更（允许生产库已存在 md 行）
        conn0 = sqlite3.connect(str(dst))
        try:
            before = [r[0] for r in conn0.execute("SELECT content_format FROM projects")]
        finally:
            conn0.close()
        summary = migrate_html_to_md.run(dst, dry_run=True)
        # 至少应处理到一些 html 行；若有失败需暴露
        if summary["total"] > 0:
            assert summary["roundtrip_failed"] == 0, (
                f"真实数据往返校验失败 {summary['roundtrip_failed']} 条："
                f"{summary['failures'][:3]}"
            )
            assert summary["pass_rate"] == 1.0
        # dry-run 不写库：content_format 必须与迁移前完全一致
        conn = sqlite3.connect(str(dst))
        try:
            after = [r[0] for r in conn.execute("SELECT content_format FROM projects")]
        finally:
            conn.close()
        assert before == after, (
            f"dry-run 不应修改 content_format：{before} -> {after}"
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_period_file_versions_stores_md_and_restore_preserves_md(tmp_path):
    """T05 新范围 item5：period_file_versions 以 md_content + file_format='md' 存储，
    restore 复制 md_content（不回退为 docx BLOB）。"""
    from backend.database import Database

    db_path = tmp_path / "pfx.db"
    db = Database(db_path)
    cat = db.create_category(name="QA分类", path="QA分类")
    cid = cat["id"]

    sample_md = "# 周期文档\n\n- 项目A\n- 项目B\n"
    db.save_period_file_version(
        category_id=cid,
        period_type="week",
        period_label="2026-W32",
        relative_path="by_week/2026-W32/test_week_2026-W32.md",
        word_filename="test_week_2026-W32.md",
        project_count=2,
        md_content=sample_md,
        file_format="md",
        file_sha256="x",
        source_sha256="y",
    )
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT md_content, file_format FROM period_file_versions"
        ).fetchone()
    finally:
        conn.close()
    assert row[0] == sample_md, "md_content 未正确入库"
    assert row[1] == "md", "file_format 应为 'md'"

    conn = sqlite3.connect(str(db_path))
    try:
        vid = conn.execute("SELECT id FROM period_file_versions").fetchone()[0]
    finally:
        conn.close()
    restored = db.restore_period_file_version(vid)
    assert restored["md_content"] == sample_md, "restore 丢失 md_content"
    assert restored["file_format"] == "md", "restore 未保持 file_format='md'"
