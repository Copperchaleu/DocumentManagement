"""一键回滚脚本：Markdown 真源 → 原 HTML 真源。

选取 ``content_format = 'md' AND content_html_backup IS NOT NULL`` 的条目，
将 ``content`` 写回原始 HTML、``content_format`` 置回 ``'html'``、
``content_html_backup`` 清空。与迁移脚本构成可逆闭环（满足 P0-5）。

安全约定：
- 默认 **dry-run**（不写库）。真正回滚需 ``--no-dry-run``。
- 运行前强制 ``Database.backup_to()``。
- 无 ``content_html_backup`` 的行（MD-only 新内容）不回滚。
- 支持 ``--project-id`` 单条、``--rebuild`` 触发受影响周期 Word 重建。

注：``--rebuild`` 会导入 ``backend.main`` 以复用 ``rebuild_period_markdown``，
从而触发应用启动逻辑（分类种子等）。不传则仅回滚数据并打印需重建的周期。
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.database import Database  # noqa: E402


def backup_database(db: Database, db_path: Path) -> Path:
    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = backup_dir / f"app_{stamp}.db"
    return db.backup_to(backup_path)


def run(
    db_path: Path,
    dry_run: bool = True,
    project_id: Optional[int] = None,
    rebuild: bool = False,
) -> dict:
    db = Database(db_path)
    backup_path = backup_database(db, db_path)
    print(f"[rollback] 已备份：{backup_path}")

    sql = (
        "SELECT id, category_id, content_html_backup "
        "FROM projects WHERE content_format = 'md' AND content_html_backup IS NOT NULL"
    )
    params: list = []
    if project_id is not None:
        sql += " AND id = ?"
        params.append(project_id)
    sql += " ORDER BY id ASC"

    with db.connect() as conn:
        rows = conn.execute(sql, params).fetchall()

    total = len(rows)
    written = 0
    skipped = 0
    affected_periods: set[tuple[int, str, str]] = set()

    # 周期标签列名映射（与 main.collect_period_targets 一致）。
    period_cols = [("week_label", "week"), ("month_label", "month"), ("quarter_label", "quarter")]

    for row in rows:
        pid = int(row["id"])
        backup_html = row["content_html_backup"] or ""
        if not backup_html:
            continue
        if dry_run:
            skipped += 1
            continue
        with db.connect() as wconn:
            wconn.execute(
                """
                UPDATE projects
                SET content = ?, content_format = 'html', content_html_backup = NULL
                WHERE id = ?
                """,
                (backup_html, pid),
            )
        written += 1

        # 收集受影响周期（用于重建 Word 恢复为 HTML 真源）。
        with db.connect() as rconn:
            labels = rconn.execute(
                "SELECT category_id, week_label, month_label, quarter_label "
                "FROM projects WHERE id = ?",
                (pid,),
            ).fetchone()
        if labels:
            cid = int(labels["category_id"])
            for col, ptype in period_cols:
                lab = labels[col]
                if lab:
                    affected_periods.add((cid, ptype, lab))

    # 回滚后重建受影响周期（恢复为 HTML 真源渲染的 Markdown）。
    if not dry_run and rebuild and affected_periods:
        print(f"[rollback] 重建 {len(affected_periods)} 个受影响周期 Markdown…")
        from backend.main import rebuild_period_markdown

        for cid, ptype, lab in sorted(affected_periods):
            try:
                rebuild_period_markdown(cid, ptype, lab, change_reason="回滚至 HTML 真源")
            except Exception as exc:
                print(f"[rollback] 重建 {cid}/{ptype}/{lab} 失败：{exc}")

    print(
        f"[rollback] {'[DRY-RUN] ' if dry_run else ''}"
        f"待回滚={total} 写入={written} 跳过={skipped}"
    )
    if not dry_run and rebuild:
        print(f"[rollback] 受影响周期数：{len(affected_periods)}")

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "db_path": str(db_path),
        "dry_run": dry_run,
        "backup_path": str(backup_path),
        "total": total,
        "written": written,
        "skipped": skipped,
        "affected_periods": [list(p) for p in sorted(affected_periods)],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Markdown → HTML 一键回滚")
    parser.add_argument(
        "--db",
        default=str(ROOT_DIR / "data" / "app.db"),
        help="目标数据库路径（默认 data/app.db）",
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=True, help="只统计、不写库（默认开启）"
    )
    parser.add_argument("--no-dry-run", action="store_true", help="真正执行回滚")
    parser.add_argument("--project-id", type=int, default=None, help="仅回滚指定 project_id")
    parser.add_argument(
        "--rebuild", action="store_true", help="回滚后重建受影响周期 Markdown"
    )
    args = parser.parse_args()

    dry_run = args.dry_run and not args.no_dry_run
    run(
        Path(args.db),
        dry_run=dry_run,
        project_id=args.project_id,
        rebuild=args.rebuild,
    )


if __name__ == "__main__":
    main()
