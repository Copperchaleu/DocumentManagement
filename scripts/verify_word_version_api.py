"""使用临时数据库验证项目保存到 Word 历史版本的完整 API 链路。"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend import main as backend_main  # noqa: E402
from backend.database import Database  # noqa: E402


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="word-version-api-") as tmp:
        root = Path(tmp)
        backend_main.db = Database(root / "app.db")
        backend_main.CFG["db_backup_enabled"] = False
        category = backend_main.db.create_category(
            "API测试",
            path=str(root / "documents"),
        )
        first = asyncio.run(
            backend_main.save_project(
                content="<p>第一版正文</p>",
                category_id=category["id"],
                title="版本测试",
                time_modes="month",
                project_id=None,
                client_save_token="test_first",
                files=[],
            )
        )
        assert len(first["period_files"]) == 1

        second = asyncio.run(
            backend_main.save_project(
                content="<p>第二版正文</p>",
                category_id=category["id"],
                title="版本测试",
                time_modes="month",
                project_id=first["id"],
                client_save_token="test_second",
                files=[],
            )
        )
        period_file = second["period_files"][0]
        history = backend_main.list_period_file_versions(period_file["id"])
        assert [item["version_no"] for item in history["items"]] == [2, 1]
        first_version = history["items"][-1]
        latest_version = history["items"][0]

        first_download = backend_main.download_period_file_version(
            first_version["id"]
        )
        assert first_download.status_code == 200

        local_path = root / "documents" / period_file["relative_path"]
        assert local_path.exists()
        # 模拟用户手工把本地 Word 改成另一份有效内容；下一次项目保存前必须先留版。
        local_path.write_bytes(first_download.body)
        third = asyncio.run(
            backend_main.save_project(
                content="<p>第三版正文</p>",
                category_id=category["id"],
                title="版本测试",
                time_modes="month",
                project_id=first["id"],
                client_save_token="test_third",
                files=[],
            )
        )
        period_file = third["period_files"][0]
        captured_history = backend_main.list_period_file_versions(period_file["id"])
        assert [item["version_no"] for item in captured_history["items"]] == [4, 3, 2, 1], captured_history
        assert captured_history["items"][1]["change_reason"] == "生成新版本前收录本地 Word 手工修改"

        local_path.unlink()
        latest_download = backend_main.download_period_file(
            category_id=category["id"],
            period_type="month",
            period_label=period_file["period_label"],
        )
        assert latest_download.status_code == 200
        assert local_path.exists()
        assert Path(latest_download.path).read_bytes() == local_path.read_bytes()
        assert latest_version["file_sha256"] != first_version["file_sha256"]

        restored = backend_main.restore_period_file_version(first_version["id"])
        assert restored["restored_version_no"] == 5
        assert local_path.read_bytes() == first_download.body
        final_history = backend_main.list_period_file_versions(period_file["id"])
        assert [item["version_no"] for item in final_history["items"]] == [5, 4, 3, 2, 1]
        assert final_history["items"][0]["is_current"] is True

        print("Word version API verification OK")


if __name__ == "__main__":
    main()
