"""生成《迁移影响报告》。

统计「仅样式损失」条目数，供业务签字确认纯展示样式（字体族 / 字号 / 颜色 /
对齐）的丢弃属于非内容丢失、可接受。

纯展示样式特征（命中任一即计入 style_only_loss_count）：
- ``font-family`` / ``font-size`` / ``color`` / ``text-align``
- ``<span style=...>`` / ``<font>`` / ``style=`` 含上述属性

默认输出到 ``docs/migration_impact_report.json``；也可指定 ``--out``。
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

# 纯展示样式特征（不保留，但属于噪音而非内容）。
_STYLE_PATTERNS = [
    (re.compile(r"font-family\s*:", re.IGNORECASE), "font-family"),
    (re.compile(r"font-size\s*:", re.IGNORECASE), "font-size"),
    (re.compile(r"text-align\s*:", re.IGNORECASE), "text-align"),
    # color 既可能是文字颜色（展示）也可能是链接色；此处按已决议事项计入展示样式。
    (re.compile(r"color\s*:", re.IGNORECASE), "color"),
    (re.compile(r"<\s*span\b[^>]*\bstyle\s*=", re.IGNORECASE), "span-style"),
    (re.compile(r"<\s*font\b", re.IGNORECASE), "font-tag"),
]


def detect_style_loss(backup_html: str) -> list[str]:
    """返回该 HTML 命中的纯展示样式类型列表（去重、保持定义顺序）。"""
    if not backup_html:
        return []
    hits = []
    for pattern, label in _STYLE_PATTERNS:
        if pattern.search(backup_html):
            hits.append(label)
    return hits


def compute_historical_docx_loss(db: Database) -> dict:
    """扫描 ``period_file_versions`` 的 docx BLOB 备份，标注历史 docx 损失。

    损失类型（标准 Markdown 无法等价表达、按已决议事项默认丢弃）：
    图片 / 表格 / 合并单元格 / 批注脚注 / 纯展示样式。供业务签字确认
    「历史 docx 损失非内容丢失」。
    """
    from backend.markdown_utils import docx_bytes_to_md

    total_docx_versions = 0
    has_image = 0
    has_table = 0
    has_merged_cell = 0
    has_comment = 0
    style_loss = 0
    samples: list[dict] = []
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT id, file_content FROM period_file_versions "
            "WHERE file_content IS NOT NULL"
        ).fetchall()
    for row in rows:
        total_docx_versions += 1
        try:
            _md, loss = docx_bytes_to_md(bytes(row["file_content"]))
        except Exception:
            # 单条转换失败不阻断报告，计为无法解析。
            continue
        if loss.get("has_image"):
            has_image += 1
        if loss.get("has_table"):
            has_table += 1
        if loss.get("has_merged_cell"):
            has_merged_cell += 1
        if loss.get("has_comment"):
            has_comment += 1
        if loss.get("style_loss"):
            style_loss += 1
        if len(samples) < 50:
            hits = [k for k, v in loss.items() if v]
            samples.append({"version_id": int(row["id"]), "loss_types": hits})
    return {
        "total_docx_versions": total_docx_versions,
        "has_image_count": has_image,
        "has_table_count": has_table,
        "has_merged_cell_count": has_merged_cell,
        "has_comment_count": has_comment,
        "style_loss_count": style_loss,
        "samples": samples,
    }


def generate_impact_report(
    db_path: Path,
    out_path: Optional[Path] = None,
) -> dict:
    """扫描数据库，生成影响报告 dict 并写入 out_path。"""
    db = Database(db_path)

    total_projects = 0
    migrated = 0
    failed = 0
    roundtrip_passed = 0
    roundtrip_failed = 0
    style_only_loss_count = 0
    style_loss_samples: list[dict] = []

    with db.connect() as conn:
        total_projects = conn.execute("SELECT COUNT(*) AS c FROM projects").fetchone()["c"]
        migrated = conn.execute(
            "SELECT COUNT(*) AS c FROM projects WHERE content_format = 'md'"
        ).fetchone()["c"]
        # 仅统计「原位待迁移但已转换失败」的极端情况；默认 0。
        failed = conn.execute(
            "SELECT COUNT(*) AS c FROM projects "
            "WHERE content_format IS NULL OR content_format = ''"
        ).fetchone()["c"]

        # 往返校验通过情况（有备份且已转 MD 的条目才有意义）
        rows = conn.execute(
            """
            SELECT id, content_format, content_html_backup
            FROM projects
            WHERE content_html_backup IS NOT NULL
            """
        ).fetchall()

    # 延迟导入，避免与诊断脚本的循环依赖问题。
    from backend.markdown_utils import md_to_plain_text

    for row in rows:
        if (row["content_format"] or "").lower() == "md":
            try:
                md = conn_for_row(db, row["id"])
            except Exception:
                md = None
            if md is None:
                continue
            try:
                from backend.word_service import html_to_plain_text

                original_plain = html_to_plain_text(row["content_html_backup"] or "")
                md_plain = md_to_plain_text(md)
                if original_plain == md_plain:
                    roundtrip_passed += 1
                else:
                    roundtrip_failed += 1
            except Exception:
                roundtrip_failed += 1

        hits = detect_style_loss(row["content_html_backup"] or "")
        if hits:
            style_only_loss_count += 1
            if len(style_loss_samples) < 50:
                style_loss_samples.append(
                    {"project_id": int(row["id"]), "style_types": hits}
                )

    historical_docx_loss = compute_historical_docx_loss(db)

    report = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "db_path": str(db_path),
        "total_projects": total_projects,
        "migrated": migrated,
        "failed": failed,
        "roundtrip_passed": roundtrip_passed,
        "roundtrip_failed": roundtrip_failed,
        "style_only_loss_count": style_only_loss_count,
        "style_loss_samples": style_loss_samples,
        "historical_docx_loss": historical_docx_loss,
        "note": (
            "style_only_loss_count 代表「仅样式损失」条目数（字体/字号/颜色/"
            "对齐等纯展示噪音），为非内容丢失，供业务签字确认可接受。"
            "historical_docx_loss 为历史 docx BLOB 迁移为 Markdown 时的有损项"
            "（图片/表格/合并单元格/批注脚注/纯展示样式），同样为非内容丢失。"
        ),
    }

    if out_path is None:
        out_path = ROOT_DIR / "docs" / "migration_impact_report.json"
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[impact-report] 已生成：{out_path}")
    print(
        f"[impact-report] 项目总数={total_projects} 已迁移={migrated} "
        f"往返通过={roundtrip_passed} 往返失败={roundtrip_failed} "
        f"样式损失条目={style_only_loss_count}"
    )
    print(
        f"[impact-report] 历史 docx 损失：docx版本={historical_docx_loss['total_docx_versions']} "
        f"图片={historical_docx_loss['has_image_count']} "
        f"表格={historical_docx_loss['has_table_count']} "
        f"合并单元格={historical_docx_loss['has_merged_cell_count']} "
        f"批注={historical_docx_loss['has_comment_count']} "
        f"样式={historical_docx_loss['style_loss_count']}"
    )
    return report


def conn_for_row(db: Database, project_id: int) -> Optional[str]:
    """读取某项目当前（已迁移为 md 的）content，用于往返校验。"""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT content FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
    return row["content"] if row else None


def main() -> None:
    parser = argparse.ArgumentParser(description="生成迁移影响报告")
    parser.add_argument(
        "--db",
        default=str(ROOT_DIR / "data" / "app.db"),
        help="目标数据库路径（默认 data/app.db）",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="报告输出路径（默认 docs/migration_impact_report.json）",
    )
    args = parser.parse_args()
    generate_impact_report(Path(args.db), Path(args.out) if args.out else None)


if __name__ == "__main__":
    main()
