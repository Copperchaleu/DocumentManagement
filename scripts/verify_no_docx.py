"""全链路无 .docx 验证（T09 / T05 扩展）。

断言（设计 §8.2）：
1. 代码层：backend/ 无 ``import docx`` / ``from docx``；无 ``write_docx_bytes_atomic``
   / ``build_period_word_document`` 定义或调用；requirements.txt 无 python-docx。
2. 数据层：``period_file_versions`` 全部 ``file_format='md'`` 且 ``md_content`` 非空。
3. 文件系统：``data/documents`` 下无应用新生成的 ``.docx``（仅 ``_legacy_docx/``
   归档项允许，不对外服务）。

退出码：0=通过，1=存在 .docx 残留或违规。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
BACKEND_DIR = ROOT_DIR / "backend"
REQ_PATH = ROOT_DIR / "requirements.txt"

# 过渡期对未迁移 docx 的「可读回退」是设计允许的（§4.1），以下为过渡兼容代码中的
# 合法 docx 引用关键词（注释/回退分支），不计入「写出/生成」违规。
_ALLOWED_DOCX_HITS = ("transition", "回退", "fallback", "legacy", "历史 docx")


def _code_violations() -> list[str]:
    violations: list[str] = []
    # 1) python-docx 运行依赖
    if REQ_PATH.exists():
        for line in REQ_PATH.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "python-docx" in stripped:
                violations.append(f"requirements.txt 仍含 python-docx：{stripped}")

    # 2) backend 源码：docx 导入 / 写出入口
    if BACKEND_DIR.exists():
        for path in BACKEND_DIR.rglob("*.py"):
            try:
                text = path.read_text(encoding="utf-8")
            except Exception:
                continue
            for ln_no, line in enumerate(text.splitlines(), 1):
                s = line.strip()
                if s.startswith("import docx") or s.startswith("from docx"):
                    violations.append(f"{path}:{ln_no} 仍有 docx 导入：{s}")
                if "write_docx_bytes_atomic" in line or "build_period_word_document" in line:
                    violations.append(f"{path}:{ln_no} 仍有 docx 写出入口：{s}")
    return violations


def _data_violations(db_path: Path) -> tuple[list[str], dict]:
    from backend.database import Database

    if db_path is None:
        db_path = ROOT_DIR / "data" / "app.db"
    stats = {
        "total_versions": 0,
        "docx_versions": 0,
        "empty_md_versions": 0,
    }
    if not db_path.exists():
        return [], stats
    db = Database(db_path)
    with db.connect() as conn:
        stats["total_versions"] = conn.execute(
            "SELECT COUNT(*) AS c FROM period_file_versions"
        ).fetchone()["c"]
        stats["docx_versions"] = conn.execute(
            "SELECT COUNT(*) AS c FROM period_file_versions WHERE file_format = 'docx'"
        ).fetchone()["c"]
        stats["empty_md_versions"] = conn.execute(
            "SELECT COUNT(*) AS c FROM period_file_versions "
            "WHERE file_format = 'md' AND (md_content IS NULL OR md_content = '')"
        ).fetchone()["c"]
    violations: list[str] = []
    if stats["docx_versions"] > 0:
        violations.append(
            f"仍有 {stats['docx_versions']} 条 period_file_versions 为 docx 真源（待迁移）"
        )
    if stats["empty_md_versions"] > 0:
        violations.append(
            f"有 {stats['empty_md_versions']} 条 md 版本 md_content 为空（数据丢失）"
        )
    return violations, stats


def _fs_violations(docs_dir: Path) -> tuple[list[str], int]:
    if docs_dir is None:
        docs_dir = ROOT_DIR / "data" / "documents"
    legacy_dir = docs_dir / "_legacy_docx"
    violations: list[str] = []
    count = 0
    if not docs_dir.exists():
        return violations, count
    for docx in docs_dir.rglob("*.docx"):
        if legacy_dir in docx.parents or docx.parent == legacy_dir:
            continue
        violations.append(f"应用目录存在未归档 .docx：{docx}")
        count += 1
    return violations, count


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="全链路无 .docx 验证")
    parser.add_argument(
        "--db",
        default=None,
        help="目标数据库路径（默认 <repo>/data/app.db；临时验证请指向副本）",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="周期文档根目录（默认 <repo>/data/documents；临时验证请指向副本）",
    )
    args = parser.parse_args()

    db_path = Path(args.db) if args.db else None
    data_dir = Path(args.data_dir) if args.data_dir else None

    print("=== 全链路无 .docx 验证 ===")
    all_violations: list[str] = []

    code_v = _code_violations()
    for v in code_v:
        print(f"[代码层] ✗ {v}")
    all_violations.extend(code_v)

    data_v, stats = _data_violations(db_path)
    print(
        f"[数据层] 版本总数={stats['total_versions']} "
        f"docx真源={stats['docx_versions']} 空md={stats['empty_md_versions']}"
    )
    for v in data_v:
        print(f"[数据层] ✗ {v}")
    all_violations.extend(data_v)

    fs_v, fs_count = _fs_violations(data_dir)
    print(f"[文件系统] 未归档 .docx 数={fs_count}")
    for v in fs_v:
        print(f"[文件系统] ✗ {v}")
    all_violations.extend(fs_v)

    if all_violations:
        print(f"\n结果：失败（{len(all_violations)} 项违规）")
        return 1
    print("\n结果：通过（全链路无 .docx 残留）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
