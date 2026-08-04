"""隔离验证数据库备份设置、手动备份、数量清理、下载和删除。"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend import main as backend_main  # noqa: E402
from backend.database import Database  # noqa: E402


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="backup-settings-") as tmp:
        root = Path(tmp)
        backup_dir = root / "external-backups"
        backend_main.DATA_DIR = root
        backend_main.DB_PATH = root / "app.db"
        backend_main.CONFIG_PATH = root / "config.json"
        backend_main.db = Database(backend_main.DB_PATH)
        backend_main.CFG.update(
            {
                "db_backup_enabled": True,
                "db_backup_dir": str(backup_dir),
                "db_backup_interval_hours": 24,
                "db_backup_keep": 2,
            }
        )
        backend_main.db.create_category("备份测试", path=str(root / "documents"))

        settings = backend_main.update_database_backup_settings(
            backend_main.DatabaseBackupSettingsUpdate(
                enabled=True,
                directory=str(backup_dir),
                interval_hours=6,
                max_backups=2,
            )
        )
        assert settings["settings"]["interval_hours"] == 6
        assert settings["settings"]["max_backups"] == 2
        persisted = json.loads(backend_main.CONFIG_PATH.read_text(encoding="utf-8"))
        assert persisted["db_backup_dir"] == str(backup_dir)

        for index in range(3):
            backend_main.db.create_category(
                f"分类{index}",
                path=str(root / "documents" / str(index)),
            )
            backend_main.create_database_backup()

        listed = backend_main.list_database_backups()
        assert listed["total"] == 2
        assert len(list(backup_dir.glob("app_*.db"))) == 2

        newest = listed["items"][0]
        download = backend_main.download_database_backup(newest["filename"])
        assert Path(download.path).is_file()
        backend_main.delete_database_backup(newest["filename"])
        assert backend_main.list_database_backups()["total"] == 1

        info = backend_main.get_database_backup_settings()
        assert info["summary"]["backup_count"] == 1
        assert info["database"]["path"] == str(backend_main.DB_PATH)

        print("Database backup settings verification OK")


if __name__ == "__main__":
    main()
