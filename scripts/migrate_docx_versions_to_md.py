"""历史 period_file_versions .docx BLOB → Markdown 幂等迁移脚本。

安全约定（与 migrate_html_to_md.py 一致）：
- 默认 **dry-run**（只统计、不写库）。要真正执行需显式 ``--no-dry-run``。
- 运行前强制 ``Database.backup_to()`` 全量在线备份（含 docx BLOB）。
- 仅处理 ``file_format = 'docx'`` 的行；转换后写 ``md_content``、置
  ``file_format = 'md'``，重跑自然跳过（幂等）。``file_content`` BLOB 保留
  作历史 docx 回滚备份。
- 标注损失（图片/表格/批注/纯展示样式）写入
  ``docs/historical_docx_loss.json``，供《迁移影响报告》汇总。

可选 ``--archive-legacy``：把 ``data/documents/**`` 下现存本地 ``.docx`` 移至
``data/documents/_legacy_docx/``（不对外服务），完成「全链路无 .docx」收尾。

全量统一：迁移同时把 ``period_files`` 的 ``word_filename`` / ``relative_path``
由 ``.docx`` 改写为 ``.md``，使条目与历史版本 1:1 对应、命名一致。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.database import Database  # noqa: E402
from backend.markdown_utils import docx_bytes_to_md  # noqa: E402


def backup_database(db: Database, db_path: Path) -> Path:
    """运行前全量在线备份，返回备份路径。"""
    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = backup_dir / f"app_{stamp}.db"
    return db.backup_to(backup_path)


def _rewrite_period_file_paths(db: Database) -> int:
    """把 period_files 的 word_filename/relative_path 由 .docx 改写为 .md。

    与版本迁移同步，保证条目命名一致（设计 §2.3）。幂等：仅改写仍以
    ``.docx`` 结尾的行。返回改写条数。
    """
    rewritten = 0
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT id, word_filename, relative_path FROM period_files "
            "WHERE word_filename LIKE '%.docx'"
        ).fetchall()
        for row in rows:
            new_name = row["word_filename"][:-5] + ".md"
            new_rel = (row["relative_path"] or "").rsplit(".docx", 1)[0] + ".md"
            conn.execute(
                "UPDATE period_files SET word_filename = ?, relative_path = ? "
                "WHERE id = ?",
                (new_name, new_rel, int(row["id"])),
            )
            rewritten += 1
    return rewritten


def _archive_legacy_docx(documents_dir: Path, legacy_dir: Path) -> int:
    """把现存本地 .docx（非 _legacy_docx）移至 _legacy_docx，返回移动数。"""
    if not documents_dir.exists():
        return 0
    legacy_dir.mkdir(parents=True, exist_ok=True)
    moved = 0
    for docx in documents_dir.rglob("*.docx"):
        if legacy_dir in docx.parents or docx.parent == legacy_dir:
            continue
        rel = docx.relative_to(documents_dir)
        dest = legacy_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(docx), str(dest))
        moved += 1
    return moved


def run(
    db_path: Path,
    dry_run: bool = True,
    limit: Optional[int] = None,
    version_id: Optional[int] = None,
    archive_legacy: bool = False,
    documents_dir: Optional[Path] = None,
) -> dict:
    db = Database(db_path)
    backup_path = backup_database(db, db_path)
    print(f"[migrate-docx] 已备份：{backup_path}")

    sql = (
        "SELECT id, file_content FROM period_file_versions "
        "WHERE file_format = 'docx' AND file_content IS NOT NULL"
    )
    params: list = []
    if version_id is not None:
        sql += " AND id = ?"
        params.append(version_id)
    sql += " ORDER BY id ASC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)

    with db.connect() as conn:
        rows = conn.execute(sql, params).fetchall()

    total = len(rows)
    converted = 0
    skipped = 0
    written = 0
    samples: list[dict] = []
    loss_acc = {
        "has_image": 0,
        "has_table": 0,
        "has_merged_cell": 0,
        "has_comment": 0,
        "style_loss": 0,
    }

    for row in rows:
        vid = int(row["id"])
        try:
            md, loss = docx_bytes_to_md(bytes(row["file_content"]))
        except Exception as exc:  # 单条转换失败不影响其它，记录后跳过
            print(f"[migrate-docx] 版本 {vid} 转换失败：{exc}")
            skipped += 1
            continue

        converted += 1
        for key in loss_acc:
            if loss.get(key):
                loss_acc[key] += 1
        if len(samples) < 50:
            hits = [k for k, v in loss.items() if v]
            samples.append({"version_id": vid, "loss_types": hits})

        if dry_run:
            skipped += 1
            continue

        with db.connect() as wconn:
            wconn.execute(
                """
                UPDATE period_file_versions
                SET md_content = ?, file_format = 'md'
                WHERE id = ?
                """,
                (md, vid),
            )
        written += 1

    # period_files 路径 .docx → .md（仅 --no-dry-run 真正改写）
    paths_rewritten = 0
    if not dry_run:
        paths_rewritten = _rewrite_period_file_paths(db)

    # 可选：归档历史本地 .docx
    legacy_moved = 0
    if archive_legacy and not dry_run:
        docs_root = Path(documents_dir) if documents_dir else (ROOT_DIR / "data" / "documents")
        legacy_moved = _archive_legacy_docx(
            docs_root, docs_root / "_legacy_docx"
        )

    historical_loss = {
        "total_docx_versions": total,
        "converted": converted,
        "has_image_count": loss_acc["has_image"],
        "has_table_count": loss_acc["has_table"],
        "has_merged_cell_count": loss_acc["has_merged_cell"],
        "has_comment_count": loss_acc["has_comment"],
        "style_loss_count": loss_acc["style_loss"],
        "samples": samples,
    }

    summary = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "db_path": str(db_path),
        "dry_run": dry_run,
        "backup_path": str(backup_path),
        "total_docx_versions": total,
        "converted": converted,
        "written": written,
        "skipped": skipped,
        "period_file_paths_rewritten": paths_rewritten,
        "legacy_docx_archived": legacy_moved,
        "historical_docx_loss": historical_loss,
    }

    loss_path = ROOT_DIR / "docs" / "historical_docx_loss.json"
    loss_path.parent.mkdir(parents=True, exist_ok=True)
    loss_path.write_text(
        json.dumps(historical_loss, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[migrate-docx] 损失报告：{loss_path}")

    out_path = ROOT_DIR / "docs" / "docx_migration_summary.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"[migrate-docx] {'[DRY-RUN] ' if dry_run else ''}总={total} "
        f"转换={converted} 写入={written} 跳过={skipped} "
        f"路径改写={paths_rewritten} 归档docx={legacy_moved}"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="历史 period_file_versions .docx → Markdown 迁移")
    parser.add_argument(
        "--db",
        default=str(ROOT_DIR / "data" / "app.db"),
        help="目标数据库路径（默认 data/app.db）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="只统计、不写库（默认开启）",
    )
    parser.add_argument(
        "--no-dry-run",
        action="store_true",
        help="真正执行迁移写入（请先确认已备份）",
    )
    parser.add_argument("--limit", type=int, default=None, help="仅处理前 N 条（灰度）")
    parser.add_argument(
        "--version-id", type=int, default=None, help="仅处理指定 version_id"
    )
    parser.add_argument(
        "--archive-legacy",
        action="store_true",
        help="迁移后把现存本地 .docx 归档至 <documents-dir>/_legacy_docx/",
    )
    parser.add_argument(
        "--documents-dir",
        default=None,
        help="本地周期文档根目录（仅 --archive-legacy 使用；默认 <repo>/data/documents）",
    )
    args = parser.parse_args()

    dry_run = args.dry_run and not args.no_dry_run
    run(
        Path(args.db),
        dry_run=dry_run,
        limit=args.limit,
        version_id=args.version_id,
        archive_legacy=args.archive_legacy,
        documents_dir=Path(args.documents_dir) if args.documents_dir else None,
    )


if __name__ == "__main__":
    main()
