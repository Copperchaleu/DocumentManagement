"""隔离验证 Markdown 周期版本、去重、本地同步和恢复审计。

（原 Word BLOB 验证脚本的 Markdown 等价版：Word 全链路已移除，周期文档改为
Markdown 文本列 ``md_content`` 存储，版本语义——去重 / 本地同步 / 恢复审计 /
在线备份——保持不变。）
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.database import Database
from backend.word_service import build_period_markdown_document, write_file_atomic


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def save_version(
    db: Database,
    *,
    category_id: int,
    content: str,
    source_text: str,
    reason: str,
) -> dict:
    snapshot = json.dumps({"source": source_text}, ensure_ascii=False, sort_keys=True)
    return db.save_period_file_version(
        category_id=category_id,
        period_type="month",
        period_label="2026-08",
        relative_path="by_month/2026-08/测试_month_2026-08.md",
        word_filename="测试_month_2026-08.md",
        project_count=1,
        md_content=content,
        file_format="md",
        file_sha256=sha256(content.encode("utf-8")),
        source_sha256=sha256(snapshot.encode("utf-8")),
        source_snapshot_json=snapshot,
        change_reason=reason,
    )


def _project(title: str, content: str, updated_at: str) -> dict:
    return {
        "id": 1,
        "title": title,
        "content": content,
        "created_at": "2026-08-04 10:00:00",
        "updated_at": updated_at,
        "attachments": [],
    }


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="md-version-check-") as tmp:
        root = Path(tmp)

        # 验证旧版 period_files 表可以原地补列并创建版本表。
        legacy_path = root / "legacy.db"
        legacy = sqlite3.connect(legacy_path)
        legacy.executescript(
            """
            CREATE TABLE categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                path TEXT DEFAULT '',
                description TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE period_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id INTEGER NOT NULL,
                period_type TEXT NOT NULL,
                period_label TEXT NOT NULL,
                relative_path TEXT NOT NULL,
                word_filename TEXT NOT NULL,
                project_count INTEGER DEFAULT 0,
                updated_at TEXT NOT NULL,
                UNIQUE(category_id, period_type, period_label)
            );
            """
        )
        legacy.commit()
        legacy.close()
        migrated = Database(legacy_path)
        with migrated.connect() as conn:
            period_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(period_files)")
            }
            assert "current_version_id" in period_columns
            assert conn.execute(
                "SELECT name FROM sqlite_master WHERE name = 'period_file_versions'"
            ).fetchone()

        db = Database(root / "app.db")
        category = db.create_category("测试", path=str(root / "documents"))

        first_md = build_period_markdown_document(
            category_path_names=["测试"],
            period_type="month",
            period_label="2026-08",
            projects=[_project("第一版", "<p>第一版正文</p>", "2026-08-04 10:00:00")],
        )
        first = save_version(
            db,
            category_id=category["id"],
            content=first_md,
            source_text="first",
            reason="首次保存",
        )
        assert first["version_created"] is True
        period_file_id = first["period_file"]["id"]
        assert len(db.list_period_file_versions(period_file_id)) == 1

        duplicate = save_version(
            db,
            category_id=category["id"],
            content=first_md,
            source_text="first",
            reason="重复重建",
        )
        assert duplicate["version_created"] is False
        assert len(db.list_period_file_versions(period_file_id)) == 1

        second_md = build_period_markdown_document(
            category_path_names=["测试"],
            period_type="month",
            period_label="2026-08",
            projects=[_project("第二版", "<p>第二版正文</p>", "2026-08-04 11:00:00")],
        )
        second = save_version(
            db,
            category_id=category["id"],
            content=second_md,
            source_text="second",
            reason="项目更新",
        )
        assert second["version_created"] is True
        assert len(db.list_period_file_versions(period_file_id)) == 2

        local_path = root / second["period_file"]["relative_path"]
        write_file_atomic(second_md.encode("utf-8"), local_path)
        assert local_path.read_text(encoding="utf-8") == second_md
        db.mark_period_file_sync(period_file_id, "synced")

        first_version_id = db.list_period_file_versions(period_file_id)[-1]["id"]
        restored = db.restore_period_file_version(first_version_id)
        assert restored is not None
        assert restored["version_no"] == 3
        assert restored["md_content"] == first_md
        assert len(db.list_period_file_versions(period_file_id)) == 3

        backup_path = db.backup_to(root / "backups" / "app_snapshot.db")
        backup_db = Database(backup_path)
        assert len(backup_db.list_period_file_versions(period_file_id)) == 3

        print("Markdown version verification OK")


if __name__ == "__main__":
    main()
