"""HTML → Markdown 幂等迁移脚本（含往返校验 + 影响报告）。

安全约定：
- 默认 **dry-run**（只统计、不写库）。要真正执行迁移需显式 ``--no-dry-run``。
- 运行前强制 ``Database.backup_to()`` 全量在线备份。
- 仅处理 ``content_format = 'html'`` 的行；转换后写 ``content_format = 'md'``，
  重跑自然跳过（幂等）。
- 原 HTML 写入 ``content_html_backup``，支持一键回滚。
- 支持 ``--limit N``（灰度）与 ``--project-id ID``（单条定位）。

往返校验：``original_plain = html_to_plain_text(backup)`` 与
``md_plain = md_to_plain_text(md)``（mistune→html→strip 同口径）比较，
集合与顺序一致、diff_count=0 通过该条；要求全量 100%。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.database import Database  # noqa: E402
from backend.markdown_utils import (  # noqa: E402
    get_plain_text,
    html_to_md,
    md_to_plain_text,
    sniff_content_format,
)
from backend.word_service import html_to_plain_text  # noqa: E402


def backup_database(db: Database, db_path: Path) -> Path:
    """运行前全量在线备份，返回备份路径。"""
    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = backup_dir / f"app_{stamp}.db"
    return db.backup_to(backup_path)


def _normalize_plain_text(text: str) -> list[str]:
    """归一化纯文本用于公平比较：折叠连续换行为单换行、去除行尾空白。

    背景：wangEditor 常在「单段内 <br><br>」表达空行，使 html_to_plain_text 产出
    内部 ``\\n\\n``；而 markdown 的 ``\\n\\n`` 表示段落分隔，mistune 重渲染后会被
    解析为多个块、再以单 ``\\n`` 拼接。两者「文字与顺序」完全一致，仅空行数量不同。
    折叠换行后比较，可专注判定「内容是否丢失」，同时仍能在文字/顺序真正不同时
    判 diff_count>0（触发保留 html 真源的安全兜底）。
    """
    collapsed = re.sub(r"\n+", "\n", text or "")
    return [line.rstrip() for line in collapsed.split("\n")]


def validate_roundtrip(html_backup: str, md: str) -> int:
    """比较 原 HTML 纯文本 与 MD→纯文本 的差异块数（P0-4）。

    同口径（均经 html_to_plain_text），逐行比较集合与顺序，差异行数即为
    diff_count；要求全量 diff_count=0（100%）。比较前做空白归一化，使空行数量
    差异（单段 <br><br> vs markdown 段落分隔）不误判为内容丢失。
    """
    original_plain = html_to_plain_text(html_backup or "")
    md_plain = md_to_plain_text(md)
    orig_lines = _normalize_plain_text(original_plain)
    md_lines = _normalize_plain_text(md_plain)
    n = max(len(orig_lines), len(md_lines))
    diff_count = 0
    for i in range(n):
        a = orig_lines[i] if i < len(orig_lines) else None
        b = md_lines[i] if i < len(md_lines) else None
        if a != b:
            diff_count += 1
    return diff_count


def run(
    db_path: Path,
    dry_run: bool = True,
    limit: Optional[int] = None,
    project_id: Optional[int] = None,
) -> dict:
    db = Database(db_path)

    backup_path = backup_database(db, db_path)
    print(f"[migrate] 已备份：{backup_path}")

    sql = "SELECT id, content, content_format FROM projects WHERE content_format = 'html'"
    params: list = []
    if project_id is not None:
        sql += " AND id = ?"
        params.append(project_id)
    sql += " ORDER BY id ASC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)

    with db.connect() as conn:
        rows = conn.execute(sql, params).fetchall()

    total = len(rows)
    passed = 0
    failed = 0
    written = 0
    skipped = 0
    skipped_failed = 0
    failures: list[dict] = []

    for row in rows:
        pid = int(row["id"])
        html = row["content"] or ""
        md = html_to_md(html)
        diff_count = validate_roundtrip(html, md)
        if diff_count == 0:
            passed += 1
        else:
            failed += 1
            failures.append(
                {
                    "project_id": pid,
                    "diff_count": diff_count,
                    "original_plain": html_to_plain_text(html),
                    "md_plain": md_to_plain_text(md),
                }
            )

        if dry_run:
            skipped += 1
            continue

        # 安全兜底（P0-4 上线门槛）：往返校验未通过（diff_count>0）的行
        # 保留 html 真源、不写入，避免带病迁移。待上游 HTML 修正后重跑自然迁移。
        if diff_count > 0:
            skipped_failed += 1
            continue

        preview = get_plain_text(md, "md")[:200]
        with db.connect() as wconn:
            wconn.execute(
                """
                UPDATE projects
                SET content = ?, content_format = 'md',
                    content_html_backup = ?, content_preview = ?
                WHERE id = ?
                """,
                (md, html, preview, pid),
            )
        written += 1

    summary = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "db_path": str(db_path),
        "dry_run": dry_run,
        "backup_path": str(backup_path),
        "total": total,
        "roundtrip_passed": passed,
        "roundtrip_failed": failed,
        "written": written,
        "skipped": skipped,
        "skipped_failed": skipped_failed,
        "pass_rate": (passed / total) if total else 1.0,
        "failures": failures,
    }

    out_path = ROOT_DIR / "docs" / "validation.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"[migrate] {'[DRY-RUN] ' if dry_run else ''}总={total} "
        f"往返通过={passed} 往返失败={failed} 写入={written} 跳过={skipped}"
    )
    print(f"[migrate] 校验详情：{out_path}")

    # 迁移后立即生成《影响报告》（扫描 content_html_backup 的样式损失）。
    try:
        from migration_impact_report import generate_impact_report

        generate_impact_report(db_path)
    except Exception as exc:  # 影响报告不影响迁移主流程
        print(f"[migrate] 影响报告生成失败（可稍后单独运行）：{exc}")

    if not dry_run and failed > 0:
        print(
            f"[migrate] 警告：{failed} 条往返校验未通过（diff_count>0），"
            "请复核 docs/validation.json 中的 failures 后再决定是否回滚。"
        )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="wangEditor HTML → Markdown 迁移")
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
        "--project-id", type=int, default=None, help="仅处理指定 project_id"
    )
    args = parser.parse_args()

    dry_run = args.dry_run and not args.no_dry_run
    run(
        Path(args.db),
        dry_run=dry_run,
        limit=args.limit,
        project_id=args.project_id,
    )


if __name__ == "__main__":
    main()
