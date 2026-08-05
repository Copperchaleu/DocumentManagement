"""将 data/app.db 一致性备份，并把全部有效数据迁移到适配新系统的目标库。

流程：
  1. 在线一致性备份 app.db -> app_backup.db（SQLite backup API，可并发安全）
  2. 用后端权威 schema（Database 类）在 data/app_migrated.db 建库（仅新系统表）
  3. 按依赖顺序复制全部有效数据（保留原 id / 外键 / sqlite_sequence）
  4. 多重校验：行数、逐表 SHA256 校验和、foreign_key_check、integrity_check

用法：
  python scripts/migrate_app_to_new_system.py
"""
from __future__ import annotations

import hashlib
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "app.db"
BACKUP = ROOT / "data" / "app_backup.db"
TARGET = ROOT / "data" / "app_migrated.db"

# 新系统有效表（排除旧系统遗留的 documents / attachments_legacy_docs）
SRC_TABLES = [
    "categories",
    "projects",
    "attachments",
    "period_files",
    "period_file_versions",
    "workbench_tasks",
    "workbench_notes",
]
# 整数自增表，迁移后需校正 sqlite_sequence，使后续自增从 max(id)+1 继续
AUTO_TABLES = ["categories", "projects", "attachments", "period_files", "period_file_versions"]

# 目标库（新系统 schema）中 NOT NULL、但源库历史数据可能为 NULL 的列，
# 需按运行时语义填充默认值后再写入，保证约束成立且不丢语义。
# 例：docx 历史版本的 md_content 为 NULL，按设计填 ''（仅 md 格式行才含正文）。
NOT_NULL_DEFAULTS: dict[str, dict[str, object]] = {
    "period_file_versions": {"md_content": ""},
}


def log(msg: str) -> None:
    print(msg, flush=True)


def step1_backup() -> None:
    if BACKUP.exists():
        BACKUP.unlink()
    src = sqlite3.connect(str(SRC))
    dst = sqlite3.connect(str(BACKUP))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    size = BACKUP.stat().st_size
    log(f"[1/4] 备份完成 -> {BACKUP}  ({size:,} bytes)")


def step2_create_target() -> None:
    sys.path.insert(0, str(ROOT / "backend"))
    from database import Database  # noqa: E402

    if TARGET.exists():
        TARGET.unlink()
    # 触发完整新系统 schema：_migrate -> _init_schema -> 各项补列
    Database(TARGET)
    log(f"[2/4] 目标库已按新系统 schema 创建 -> {TARGET}")


def _row_hash(row: sqlite3.Row) -> bytes:
    h = hashlib.sha256()
    for key in row.keys():
        v = row[key]
        if v is None:
            h.update(b"\x00")
        elif isinstance(v, bytes):
            h.update(v)
        else:
            h.update(str(v).encode("utf-8"))
    return h.digest()


def step3_migrate() -> tuple[dict, dict]:
    src = sqlite3.connect(str(SRC))
    src.row_factory = sqlite3.Row
    tgt = sqlite3.connect(str(TARGET))
    tgt.row_factory = sqlite3.Row

    src_counts: dict[str, int] = {}
    tgt_counts: dict[str, int] = {}
    try:
        tgt.execute("PRAGMA foreign_keys=OFF")
        for tbl in SRC_TABLES:
            src_cols = [r["name"] for r in src.execute(f"PRAGMA table_info('{tbl}')")]
            tgt_cols = [r["name"] for r in tgt.execute(f"PRAGMA table_info('{tbl}')")]
            common = [c for c in src_cols if c in tgt_cols]
            if not common:
                log(f"      ! 表 {tbl} 在目标库无对应列，跳过")
                continue
            # 对目标 NOT NULL 但源可能为 NULL 的列做 COALESCE 适配
            defaults = NOT_NULL_DEFAULTS.get(tbl, {})
            exprs, params = [], []
            for c in common:
                if c in defaults:
                    exprs.append(f"COALESCE({c}, ?) AS {c}")
                    params.append(defaults[c])
                else:
                    exprs.append(c)
            rows = src.execute(
                f"SELECT {','.join(exprs)} FROM {tbl}", params
            ).fetchall()
            src_counts[tbl] = len(rows)
            if rows:
                placeholders = ",".join(["?"] * len(common))
                col_sql = ",".join(common)
                tgt.executemany(
                    f"INSERT INTO {tbl} ({col_sql}) VALUES ({placeholders})",
                    [
                        tuple(
                            sqlite3.Binary(r[c]) if isinstance(r[c], bytes) else r[c]
                            for c in common
                        )
                        for r in rows
                    ],
                )
            tgt_counts[tbl] = tgt.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            log(f"      复制 {tbl}: {src_counts[tbl]} 行")

        # 校正 sqlite_sequence，保证后续自增从 max(id)+1 继续
        for t in AUTO_TABLES:
            mx = src.execute(f"SELECT MAX(id) FROM {t}").fetchone()[0]
            if mx is not None:
                tgt.execute(
                    "INSERT OR REPLACE INTO sqlite_sequence(name, seq) VALUES (?, ?)",
                    (t, mx),
                )
        tgt.commit()
    finally:
        tgt.execute("PRAGMA foreign_keys=ON")
        tgt.close()
        src.close()
    log("[3/4] 数据迁移完成")
    return src_counts, tgt_counts


def step4_verify(src_counts: dict, tgt_counts: dict) -> None:
    src = sqlite3.connect(str(SRC))
    src.row_factory = sqlite3.Row
    tgt = sqlite3.connect(str(TARGET))
    tgt.row_factory = sqlite3.Row
    ok = True
    try:
        # 1) 行数一致
        for tbl in SRC_TABLES:
            s = src_counts.get(tbl)
            t = tgt.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            mark = "OK" if s == t else "FAIL"
            if s != t:
                ok = False
            log(f"      行数 {tbl}: 源={s} 目标={t} [{mark}]")

        # 2) 逐表数据校验和（按 id 排序，排除空表无意义比较）
        for tbl in SRC_TABLES:
            cols = [r["name"] for r in src.execute(f"PRAGMA table_info('{tbl}')")]
            defaults = NOT_NULL_DEFAULTS.get(tbl, {})
            exprs, params = [], []
            for c in cols:
                if c in defaults:
                    exprs.append(f"COALESCE({c}, ?) AS {c}")
                    params.append(defaults[c])
                else:
                    exprs.append(c)
            srows = src.execute(
                f"SELECT {','.join(exprs)} FROM {tbl} ORDER BY id", params
            ).fetchall()
            trows = tgt.execute(
                f"SELECT {','.join(exprs)} FROM {tbl} ORDER BY id", params
            ).fetchall()
            if not srows:
                continue
            sh = hashlib.sha256()
            for r in srows:
                sh.update(_row_hash(r))
            th = hashlib.sha256()
            for r in trows:
                th.update(_row_hash(r))
            same = sh.hexdigest() == th.hexdigest()
            if not same:
                ok = False
            log(f"      校验和 {tbl}: {'一致' if same else '不一致 [FAIL]'}")

        # 3) 外键完整性
        fk = tgt.execute("PRAGMA foreign_key_check").fetchall()
        if fk:
            ok = False
            log(f"      foreign_key_check 发现 {len(fk)} 处违规 [FAIL]")
        else:
            log("      foreign_key_check: 无违规 [OK]")

        # 4) 库级完整性
        integrity = tgt.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            ok = False
            log(f"      integrity_check: {integrity} [FAIL]")
        else:
            log("      integrity_check: ok [OK]")

        # 5) 确认废弃表未进入目标库
        legacy = tgt.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name IN ('documents','attachments_legacy_docs')"
        ).fetchall()
        if legacy:
            log(f"      注意：目标库仍含废弃表 {[r['name'] for r in legacy]}（已清空）")
        else:
            log("      废弃表 documents / attachments_legacy_docs 未进入目标库 [OK]")
    finally:
        tgt.close()
        src.close()

    log("[4/4] 校验完成")
    if not ok:
        log("结果: 存在不一致，请检查上方 [FAIL] 项")
        sys.exit(1)
    log("结果: 全部校验通过，数据完整无丢失 ✅")


def main() -> None:
    if not SRC.exists():
        log(f"源库不存在: {SRC}")
        sys.exit(1)
    log(f"源库: {SRC}  ({SRC.stat().st_size:,} bytes)")
    step1_backup()
    step2_create_target()
    src_counts, tgt_counts = step3_migrate()
    step4_verify(src_counts, tgt_counts)


if __name__ == "__main__":
    main()
