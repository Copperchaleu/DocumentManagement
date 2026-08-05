"""SQLite 数据访问层（多级分类 + 项目）。"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Generator, Optional

# 哨兵：用于区分「调用方未传（保持原值）」与「显式置空/置默认值」。
_UNSET = object()


class Database:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # 先迁移旧表结构，再创建新表/索引，避免 parent_id 等新列不存在时报错
        self._migrate()
        self._init_schema()
        # 确保迁移所需新列存在（覆盖全新库与旧库）
        self._ensure_migration_columns()
        # 周期版本表新增 Markdown 文本列与格式标识（覆盖全新库与旧库）
        self._ensure_period_version_columns()

    @contextmanager
    def connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def backup_to(self, backup_path: Path) -> Path:
        """使用 SQLite 在线备份 API 创建一致性数据库快照。"""
        backup_path = Path(backup_path)
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        source = sqlite3.connect(self.db_path)
        destination = sqlite3.connect(backup_path)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
        return backup_path

    def _init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS categories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    parent_id INTEGER,
                    name TEXT NOT NULL,
                    path TEXT DEFAULT '',
                    description TEXT DEFAULT '',
                    sort_order INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (parent_id) REFERENCES categories(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    category_id INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    content_preview TEXT DEFAULT '',
                    time_modes_json TEXT NOT NULL DEFAULT '[]',
                    week_label TEXT,
                    month_label TEXT,
                    quarter_label TEXT,
                    status TEXT NOT NULL DEFAULT 'saved',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS attachments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    original_name TEXT NOT NULL,
                    stored_name TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    size INTEGER DEFAULT 0,
                    content_type TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS period_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category_id INTEGER NOT NULL,
                    period_type TEXT NOT NULL,
                    period_label TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    word_filename TEXT NOT NULL,
                    project_count INTEGER DEFAULT 0,
                    current_version_id INTEGER,
                    current_sha256 TEXT DEFAULT '',
                    current_source_sha256 TEXT DEFAULT '',
                    local_sync_status TEXT NOT NULL DEFAULT 'unknown',
                    last_sync_error TEXT DEFAULT '',
                    updated_at TEXT NOT NULL,
                    UNIQUE(category_id, period_type, period_label),
                    FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS period_file_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    period_file_id INTEGER NOT NULL,
                    version_no INTEGER NOT NULL,
                    file_content BLOB,
                    md_content TEXT NOT NULL DEFAULT '',
                    file_format TEXT NOT NULL DEFAULT 'md',
                    file_size INTEGER NOT NULL DEFAULT 0,
                    file_sha256 TEXT NOT NULL DEFAULT '',
                    source_sha256 TEXT NOT NULL DEFAULT '',
                    project_count INTEGER DEFAULT 0,
                    change_reason TEXT DEFAULT '',
                    source_snapshot_json TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE(period_file_id, version_no),
                    FOREIGN KEY (period_file_id) REFERENCES period_files(id) ON DELETE CASCADE
                );
                """
            )
            # 索引在确认列存在后创建
            cols = {
                r["name"]
                for r in conn.execute("PRAGMA table_info(categories)").fetchall()
            }
            if "parent_id" in cols:
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_categories_parent ON categories(parent_id)"
                )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_projects_category ON projects(category_id)"
            )
            att_cols = {
                r["name"]
                for r in conn.execute("PRAGMA table_info(attachments)").fetchall()
            }
            if "project_id" in att_cols:
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_attachments_project ON attachments(project_id)"
                )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_period_files_cat ON period_files(category_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_period_versions_file "
                "ON period_file_versions(period_file_id, version_no DESC)"
            )
            # 看板聚合按 created_at 归窗，补充索引提升统计性能
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_projects_created_at "
                "ON projects(created_at)"
            )

    def _migrate(self) -> None:
        """兼容旧库：补列，去掉分类全局唯一名约束，适配多级分类。"""
        with self.connect() as conn:
            # 确认表是否存在
            tables = {
                r["name"]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "categories" not in tables:
                return

            cols = {
                r["name"]
                for r in conn.execute("PRAGMA table_info(categories)").fetchall()
            }
            if "parent_id" not in cols:
                try:
                    conn.execute(
                        "ALTER TABLE categories ADD COLUMN parent_id INTEGER"
                    )
                except Exception:
                    pass
                cols.add("parent_id")
            if "sort_order" not in cols:
                try:
                    conn.execute(
                        "ALTER TABLE categories ADD COLUMN sort_order INTEGER DEFAULT 0"
                    )
                except Exception:
                    pass

            # 检测是否仍有 name 全局 UNIQUE（旧版）。若有则重建表去掉 UNIQUE。
            idx_rows = conn.execute("PRAGMA index_list(categories)").fetchall()
            need_rebuild = False
            for idx in idx_rows:
                # sqlite3.Row keys: seq, name, unique, origin, partial
                if int(idx["unique"] or 0) == 1:
                    info = conn.execute(
                        f"PRAGMA index_info('{idx['name']}')"
                    ).fetchall()
                    col_names = []
                    for ii in info:
                        # cid, name
                        if "name" in ii.keys():
                            col_names.append(ii["name"])
                    if col_names == ["name"]:
                        need_rebuild = True
                        break

            if need_rebuild:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS categories_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        parent_id INTEGER,
                        name TEXT NOT NULL,
                        path TEXT DEFAULT '',
                        description TEXT DEFAULT '',
                        sort_order INTEGER DEFAULT 0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        FOREIGN KEY (parent_id) REFERENCES categories_new(id) ON DELETE CASCADE
                    );
                    INSERT INTO categories_new
                        (id, parent_id, name, path, description, sort_order, created_at, updated_at)
                    SELECT
                        id,
                        parent_id,
                        name,
                        COALESCE(path, ''),
                        COALESCE(description, ''),
                        COALESCE(sort_order, 0),
                        created_at,
                        updated_at
                    FROM categories;
                    DROP TABLE categories;
                    ALTER TABLE categories_new RENAME TO categories;
                    CREATE INDEX IF NOT EXISTS idx_categories_parent ON categories(parent_id);
                    """
                )

            # 旧 attachments 若只有 document_id：若 projects 空，跳过业务迁移
            if "attachments" in tables:
                att_cols = {
                    r["name"]
                    for r in conn.execute("PRAGMA table_info(attachments)").fetchall()
                }
                if "document_id" in att_cols and "project_id" not in att_cols:
                    # 旧附件表与新结构不兼容：备份旧表，重建新表
                    conn.executescript(
                        """
                        ALTER TABLE attachments RENAME TO attachments_legacy_docs;
                        CREATE TABLE IF NOT EXISTS attachments (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            project_id INTEGER NOT NULL,
                            original_name TEXT NOT NULL,
                            stored_name TEXT NOT NULL,
                            relative_path TEXT NOT NULL,
                            size INTEGER DEFAULT 0,
                            content_type TEXT DEFAULT '',
                            created_at TEXT NOT NULL,
                            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
                        );
                        CREATE INDEX IF NOT EXISTS idx_attachments_project
                            ON attachments(project_id);
                        """
                    )

                # Word 历史版本：旧库仅有 period_files 元数据，需要补充当前版本/同步字段。
            if "period_files" in tables:
                period_cols = {
                    r["name"]
                    for r in conn.execute("PRAGMA table_info(period_files)").fetchall()
                }
                additions = {
                    "current_version_id": "INTEGER",
                    "current_sha256": "TEXT DEFAULT ''",
                    "current_source_sha256": "TEXT DEFAULT ''",
                    "local_sync_status": "TEXT NOT NULL DEFAULT 'unknown'",
                    "last_sync_error": "TEXT DEFAULT ''",
                }
                for col, col_type in additions.items():
                    if col not in period_cols:
                        conn.execute(
                            f"ALTER TABLE period_files ADD COLUMN {col} {col_type}"
                        )

    def _ensure_migration_columns(self) -> None:
        """确保 ``projects`` 表含 Markdown 迁移所需新列。

        同时覆盖「全新库」（_init_schema 创建的表不含新列）与「旧库」
        （已存在但缺列的库），保证零停机迁移的安全底座一致可用。
        """
        with self.connect() as conn:
            cols = {
                r["name"]
                for r in conn.execute("PRAGMA table_info(projects)").fetchall()
            }
            if "content_format" not in cols:
                conn.execute(
                    "ALTER TABLE projects ADD COLUMN content_format TEXT NOT NULL DEFAULT 'html'"
                )
            if "content_html_backup" not in cols:
                conn.execute("ALTER TABLE projects ADD COLUMN content_html_backup TEXT")
            # 历史数据无论是否含 HTML，统一标记为 html 真源（默认分发）。
            conn.execute(
                "UPDATE projects SET content_format = 'html' "
                "WHERE content_format IS NULL OR content_format = ''"
            )

    def _ensure_period_version_columns(self) -> None:
        """确保 ``period_file_versions`` 表含 Markdown 迁移所需新列。

        - ``md_content``：Markdown 文本真源列。
        - ``file_format``：分发键（'docx' 历史真源 / 'md' 主流）。
        保留 ``file_content`` BLOB 作为历史 docx 回滚备份。覆盖全新库
        （_init_schema 已含新列）与旧库（已存在但缺列的库）两种演进路径。
        """
        with self.connect() as conn:
            cols = {
                r["name"]
                for r in conn.execute("PRAGMA table_info(period_file_versions)").fetchall()
            }
            if "file_format" not in cols:
                conn.execute(
                    "ALTER TABLE period_file_versions "
                    "ADD COLUMN file_format TEXT NOT NULL DEFAULT 'docx'"
                )
            if "md_content" not in cols:
                conn.execute(
                    "ALTER TABLE period_file_versions ADD COLUMN md_content TEXT"
                )
            # 旧数据统一标记为 docx 真源（历史 BLOB 尚未迁移）。
            conn.execute(
                "UPDATE period_file_versions SET file_format = 'docx' "
                "WHERE file_format IS NULL OR file_format = ''"
            )

            # 旧库可能仍残留 file_content 的 NOT NULL 约束（迁移前曾为必填）。
            # 当前设计下 file_content 仅作历史 docx 回滚备份，平时为 NULL；
            # 否则 rebuild_period_markdown 未传 file_content 会触发 IntegrityError。
            # 此处与代码/新 schema 意图对齐：在现有事务中放宽该约束（幂等）。
            fc_info = next(
                (
                    r for r in conn.execute(
                        "PRAGMA table_info(period_file_versions)"
                    ).fetchall() if r["name"] == "file_content"
                ),
                None,
            )
            if fc_info and fc_info["notnull"] == 1:
                conn.execute("PRAGMA foreign_keys=OFF")
                # 动态取两表共有列，兼容极旧库缺列情形，避免 SELECT 列不存在
                new_cols = [
                    "id", "period_file_id", "version_no", "file_content",
                    "md_content", "file_format", "file_size", "file_sha256",
                    "source_sha256", "project_count", "change_reason",
                    "source_snapshot_json", "created_at",
                ]
                old_cols = [
                    r["name"]
                    for r in conn.execute(
                        "PRAGMA table_info(period_file_versions)"
                    ).fetchall()
                ]
                common = [c for c in new_cols if c in old_cols]
                col_sql = ", ".join(common)
                conn.execute(
                    "ALTER TABLE period_file_versions "
                    "RENAME TO period_file_versions_old"
                )
                conn.execute(
                    """
                    CREATE TABLE period_file_versions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        period_file_id INTEGER NOT NULL,
                        version_no INTEGER NOT NULL,
                        file_content BLOB,
                        md_content TEXT NOT NULL DEFAULT '',
                        file_format TEXT NOT NULL DEFAULT 'md',
                        file_size INTEGER NOT NULL DEFAULT 0,
                        file_sha256 TEXT NOT NULL DEFAULT '',
                        source_sha256 TEXT NOT NULL DEFAULT '',
                        project_count INTEGER DEFAULT 0,
                        change_reason TEXT DEFAULT '',
                        source_snapshot_json TEXT DEFAULT '',
                        created_at TEXT NOT NULL,
                        UNIQUE(period_file_id, version_no),
                        FOREIGN KEY (period_file_id)
                            REFERENCES period_files(id) ON DELETE CASCADE
                    )
                    """
                )
                conn.execute(
                    f"INSERT INTO period_file_versions ({col_sql}) "
                    f"SELECT {col_sql} FROM period_file_versions_old"
                )
                conn.execute("DROP TABLE period_file_versions_old")
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_period_versions_file "
                    "ON period_file_versions(period_file_id, version_no DESC)"
                )
                conn.execute("PRAGMA foreign_keys=ON")

    @staticmethod
    def _now() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ---------- categories (tree) ----------

    def list_categories_flat(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT c.*,
                       (SELECT COUNT(*) FROM categories ch WHERE ch.parent_id = c.id) AS child_count,
                       (SELECT COUNT(*) FROM projects p WHERE p.category_id = c.id AND p.status != 'draft') AS project_count
                FROM categories c
                ORDER BY COALESCE(c.parent_id, 0), c.sort_order, c.name COLLATE NOCASE
                """
            ).fetchall()
            items = [dict(r) for r in rows]
            # is_leaf
            for it in items:
                it["is_leaf"] = int(it.get("child_count") or 0) == 0
            return items

    def get_category_tree(self) -> list[dict[str, Any]]:
        flat = self.list_categories_flat()
        by_id: dict[int, dict[str, Any]] = {}
        roots: list[dict[str, Any]] = []
        for item in flat:
            node = dict(item)
            node["children"] = []
            by_id[item["id"]] = node
        for item in flat:
            node = by_id[item["id"]]
            pid = item.get("parent_id")
            if pid and pid in by_id:
                by_id[pid]["children"].append(node)
            else:
                roots.append(node)
        return roots

    def get_category(self, category_id: int) -> Optional[dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT c.*,
                       (SELECT COUNT(*) FROM categories ch WHERE ch.parent_id = c.id) AS child_count,
                       (SELECT COUNT(*) FROM projects p WHERE p.category_id = c.id) AS project_count
                FROM categories c
                WHERE c.id = ?
                """,
                (category_id,),
            ).fetchone()
            if not row:
                return None
            data = dict(row)
            data["is_leaf"] = int(data.get("child_count") or 0) == 0
            return data

    def get_category_path_names(self, category_id: int) -> list[str]:
        """从根到当前节点的名称链。"""
        names: list[str] = []
        current = self.get_category(category_id)
        guard = 0
        while current and guard < 50:
            names.append(current["name"])
            pid = current.get("parent_id")
            current = self.get_category(pid) if pid else None
            guard += 1
        names.reverse()
        return names

    def list_leaf_categories(self) -> list[dict[str, Any]]:
        return [c for c in self.list_categories_flat() if c.get("is_leaf")]

    def create_category(
        self,
        name: str,
        path: str = "",
        description: str = "",
        parent_id: Optional[int] = None,
        sort_order: int = 0,
    ) -> dict[str, Any]:
        now = self._now()
        with self.connect() as conn:
            # 同级名称不可重复
            if parent_id is None:
                exists = conn.execute(
                    "SELECT id FROM categories WHERE parent_id IS NULL AND name = ?",
                    (name.strip(),),
                ).fetchone()
            else:
                exists = conn.execute(
                    "SELECT id FROM categories WHERE parent_id = ? AND name = ?",
                    (parent_id, name.strip()),
                ).fetchone()
            if exists:
                raise ValueError("同级分类下名称已存在")

            if parent_id is not None:
                parent = conn.execute(
                    "SELECT id FROM categories WHERE id = ?", (parent_id,)
                ).fetchone()
                if not parent:
                    raise ValueError("父分类不存在")

            cur = conn.execute(
                """
                INSERT INTO categories
                    (parent_id, name, path, description, sort_order, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    parent_id,
                    name.strip(),
                    (path or "").strip(),
                    (description or "").strip(),
                    sort_order,
                    now,
                    now,
                ),
            )
            category_id = cur.lastrowid
            row = conn.execute(
                "SELECT * FROM categories WHERE id = ?", (category_id,)
            ).fetchone()
            data = dict(row)
            data["child_count"] = 0
            data["project_count"] = 0
            data["is_leaf"] = True
            return data

    def update_category(
        self,
        category_id: int,
        name: Optional[str] = None,
        path: Optional[str] = None,
        description: Optional[str] = None,
        parent_id: Optional[int] = ...,  # type: ignore
        sort_order: Optional[int] = None,
    ) -> Optional[dict[str, Any]]:
        current = self.get_category(category_id)
        if not current:
            return None

        new_name = name.strip() if name is not None else current["name"]
        new_path = path.strip() if path is not None else (current.get("path") or "")
        new_desc = (
            description.strip()
            if description is not None
            else (current.get("description") or "")
        )
        if parent_id is ...:
            new_parent = current.get("parent_id")
        else:
            new_parent = parent_id
        new_sort = sort_order if sort_order is not None else (current.get("sort_order") or 0)

        if new_parent is not None and int(new_parent) == int(category_id):
            raise ValueError("不能将分类设为自己的父级")

        # 防止形成环
        if new_parent is not None:
            walker = self.get_category(int(new_parent))
            guard = 0
            while walker and guard < 50:
                if walker["id"] == category_id:
                    raise ValueError("不能将分类移动到自己的子节点下")
                pid = walker.get("parent_id")
                walker = self.get_category(pid) if pid else None
                guard += 1

        now = self._now()
        with self.connect() as conn:
            # 同级重名检查
            if new_parent is None:
                exists = conn.execute(
                    """
                    SELECT id FROM categories
                    WHERE parent_id IS NULL AND name = ? AND id != ?
                    """,
                    (new_name, category_id),
                ).fetchone()
            else:
                exists = conn.execute(
                    """
                    SELECT id FROM categories
                    WHERE parent_id = ? AND name = ? AND id != ?
                    """,
                    (new_parent, new_name, category_id),
                ).fetchone()
            if exists:
                raise ValueError("同级分类下名称已存在")

            conn.execute(
                """
                UPDATE categories
                SET parent_id = ?, name = ?, path = ?, description = ?,
                    sort_order = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_parent, new_name, new_path, new_desc, new_sort, now, category_id),
            )
        return self.get_category(category_id)

    def delete_category(self, category_id: int) -> bool:
        cat = self.get_category(category_id)
        if not cat:
            return False
        with self.connect() as conn:
            # 子分类 + 项目 + 周期文件 级联删除（FK）
            cur = conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))
            return cur.rowcount > 0

    def reorder_siblings(
        self, parent_id: Optional[int], ordered_ids: list[int]
    ) -> None:
        """原子重排某父级下的全部兄弟分类（sort_order = 索引 0..n-1）。

        parent_id=None 表示根级。ordered_ids 必须覆盖该父级下全部兄弟（顺序即新顺序）。
        任一校验失败抛 ValueError，调用方转 HTTP 400，事务回滚（不改任何 sort_order）。
        """
        if not ordered_ids:
            raise ValueError("ordered_ids 不能为空")
        if len(set(ordered_ids)) != len(ordered_ids):
            raise ValueError("ordered_ids 存在重复，请提交完整的兄弟顺序")

        with self.connect() as conn:  # 单事务：成功 commit，异常 rollback（不改任何 sort_order）
            placeholders = ",".join("?" * len(ordered_ids))
            rows = conn.execute(
                f"SELECT id, parent_id FROM categories WHERE id IN ({placeholders})",
                tuple(ordered_ids),
            ).fetchall()
            found = {
                int(r["id"]): (r["parent_id"] if r["parent_id"] is not None else None)
                for r in rows
            }

            # 1) 全部存在
            missing = [cid for cid in ordered_ids if cid not in found]
            if missing:
                raise ValueError(f"存在不存在的分类：{missing[0]} 等")

            # 2) 同父（None 与 None 视为相等；非 None 严格相等）
            for cid in ordered_ids:
                cur = found[cid]
                same = (cur is None) == (parent_id is None) and (
                    cur is None or int(cur) == int(parent_id)
                )
                if not same:
                    raise ValueError("ordered_ids 包含不同父级的分类，仅允许同级重排")

            # 3) 全覆盖兄弟
            if parent_id is None:
                sibs = conn.execute(
                    "SELECT id FROM categories WHERE parent_id IS NULL"
                ).fetchall()
            else:
                sibs = conn.execute(
                    "SELECT id FROM categories WHERE parent_id = ?", (parent_id,)
                ).fetchall()
            sibling_ids = {int(r["id"]) for r in sibs}
            given = set(ordered_ids)
            if sibling_ids != given:
                miss = sorted(sibling_ids - given)
                extra = sorted(given - sibling_ids)
                if miss:
                    raise ValueError(
                        f"ordered_ids 未覆盖该父级下全部兄弟，缺少：{miss}"
                    )
                raise ValueError(
                    f"ordered_ids 包含非该父级兄弟的 id：{extra}"
                )

            # 原子写入：按给定顺序赋 sort_order = 索引
            now = self._now()
            for k, cid in enumerate(ordered_ids):
                conn.execute(
                    "UPDATE categories SET sort_order = ?, updated_at = ? WHERE id = ?",
                    (k, now, cid),
                )

    # ---------- projects ----------

    def create_project(
        self,
        title: str,
        category_id: int,
        content: str,
        content_preview: str,
        time_modes: list[str],
        week_label: Optional[str],
        month_label: Optional[str],
        quarter_label: Optional[str],
        status: str = "saved",
        content_format: str = "html",
        content_html_backup: Optional[str] = None,
    ) -> dict[str, Any]:
        now = self._now()
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO projects (
                    title, category_id, content, content_preview, time_modes_json,
                    week_label, month_label, quarter_label, status,
                    content_format, content_html_backup, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    title,
                    category_id,
                    content,
                    content_preview,
                    json.dumps(time_modes, ensure_ascii=False),
                    week_label,
                    month_label,
                    quarter_label,
                    status,
                    (content_format or "html").lower(),
                    content_html_backup,
                    now,
                    now,
                ),
            )
            project_id = cur.lastrowid
        return self.get_project(project_id)  # type: ignore

    def update_project(
        self,
        project_id: int,
        title: Optional[str] = None,
        category_id: Optional[int] = None,
        content: Optional[str] = None,
        content_preview: Optional[str] = None,
        time_modes: Optional[list[str]] = None,
        week_label: Optional[str] = None,
        month_label: Optional[str] = None,
        quarter_label: Optional[str] = None,
        status: Optional[str] = None,
        clear_week: bool = False,
        clear_month: bool = False,
        clear_quarter: bool = False,
        # 哨兵：传 _UNSET 表示「不修改」；传 None 表示「显式置空」。
        content_format: object = _UNSET,
        content_html_backup: object = _UNSET,
    ) -> Optional[dict[str, Any]]:
        current = self.get_project(project_id)
        if not current:
            return None
        now = self._now()
        new_title = title if title is not None else current["title"]
        new_cat = category_id if category_id is not None else current["category_id"]
        new_content = content if content is not None else current["content"]
        new_preview = (
            content_preview
            if content_preview is not None
            else current.get("content_preview") or ""
        )
        new_format = (
            content_format if content_format is not _UNSET
            else current.get("content_format") or "html"
        )
        new_backup = (
            content_html_backup if content_html_backup is not _UNSET
            else current.get("content_html_backup")
        )
        new_modes = (
            time_modes if time_modes is not None else (current.get("time_modes") or [])
        )
        new_week = None if clear_week else (
            week_label if week_label is not None else current.get("week_label")
        )
        new_month = None if clear_month else (
            month_label if month_label is not None else current.get("month_label")
        )
        new_quarter = None if clear_quarter else (
            quarter_label if quarter_label is not None else current.get("quarter_label")
        )
        # 若传入标签参数则覆盖
        if week_label is not None:
            new_week = week_label
        if month_label is not None:
            new_month = month_label
        if quarter_label is not None:
            new_quarter = quarter_label
        new_status = status if status is not None else current.get("status") or "saved"

        with self.connect() as conn:
            conn.execute(
                """
                UPDATE projects SET
                    title = ?, category_id = ?, content = ?, content_preview = ?,
                    time_modes_json = ?, week_label = ?, month_label = ?, quarter_label = ?,
                    status = ?, content_format = ?, content_html_backup = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    new_title,
                    new_cat,
                    new_content,
                    new_preview,
                    json.dumps(new_modes, ensure_ascii=False),
                    new_week,
                    new_month,
                    new_quarter,
                    new_status,
                    (new_format or "html").lower(),
                    new_backup,
                    now,
                    project_id,
                ),
            )
        return self.get_project(project_id)

    def list_projects(
        self,
        category_id: Optional[int] = None,
        keyword: Optional[str] = None,
        include_draft: bool = False,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT p.*, c.name AS category_name, c.path AS category_path
            FROM projects p
            JOIN categories c ON c.id = p.category_id
            WHERE 1=1
        """
        params: list[Any] = []
        if not include_draft:
            sql += " AND p.status != 'draft'"
        if category_id is not None:
            # 含子分类
            leaf_ids = self._category_and_descendant_ids(category_id)
            if not leaf_ids:
                return []
            placeholders = ",".join("?" * len(leaf_ids))
            sql += f" AND p.category_id IN ({placeholders})"
            params.extend(leaf_ids)
        if keyword:
            sql += " AND (p.title LIKE ? OR p.content LIKE ?)"
            like = f"%{keyword}%"
            params.extend([like, like])
        sql += " ORDER BY p.updated_at DESC LIMIT ?"
        params.append(limit)

        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            items = [self._row_to_project(r) for r in rows]
            for item in items:
                atts = conn.execute(
                    "SELECT * FROM attachments WHERE project_id = ? ORDER BY id",
                    (item["id"],),
                ).fetchall()
                item["attachments"] = [dict(a) for a in atts]
                item["category_path_names"] = self.get_category_path_names(
                    item["category_id"]
                )
            return items

    def list_projects_for_period(
        self,
        category_id: int,
        period_type: str,
        period_label: str,
    ) -> list[dict[str, Any]]:
        """某叶子分类 + 某时间周期下的已保存项目。"""
        col = {
            "week": "week_label",
            "month": "month_label",
            "quarter": "quarter_label",
        }.get(period_type)
        if not col:
            return []
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT p.*, c.name AS category_name, c.path AS category_path
                FROM projects p
                JOIN categories c ON c.id = p.category_id
                WHERE p.category_id = ?
                  AND p.status = 'saved'
                  AND p.{col} = ?
                ORDER BY p.created_at ASC, p.id ASC
                """,
                (category_id, period_label),
            ).fetchall()
            items = [self._row_to_project(r) for r in rows]
            for item in items:
                atts = conn.execute(
                    "SELECT * FROM attachments WHERE project_id = ? ORDER BY id",
                    (item["id"],),
                ).fetchall()
                item["attachments"] = [dict(a) for a in atts]
            return items

    def get_project(self, project_id: int) -> Optional[dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT p.*, c.name AS category_name, c.path AS category_path
                FROM projects p
                JOIN categories c ON c.id = p.category_id
                WHERE p.id = ?
                """,
                (project_id,),
            ).fetchone()
            if not row:
                return None
            item = self._row_to_project(row)
            atts = conn.execute(
                "SELECT * FROM attachments WHERE project_id = ? ORDER BY id",
                (project_id,),
            ).fetchall()
            item["attachments"] = [dict(a) for a in atts]
            item["category_path_names"] = self.get_category_path_names(
                item["category_id"]
            )
            return item

    def delete_project(self, project_id: int) -> Optional[dict[str, Any]]:
        project = self.get_project(project_id)
        if not project:
            return None
        with self.connect() as conn:
            conn.execute("DELETE FROM attachments WHERE project_id = ?", (project_id,))
            conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        return project

    def add_attachment(
        self,
        project_id: int,
        original_name: str,
        stored_name: str,
        relative_path: str,
        size: int,
        content_type: str,
    ) -> dict[str, Any]:
        now = self._now()
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO attachments (
                    project_id, original_name, stored_name, relative_path,
                    size, content_type, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    original_name,
                    stored_name,
                    relative_path,
                    size,
                    content_type,
                    now,
                ),
            )
            att_id = cur.lastrowid
            row = conn.execute(
                "SELECT * FROM attachments WHERE id = ?", (att_id,)
            ).fetchone()
            return dict(row)

    def get_attachment(self, attachment_id: int) -> Optional[dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT a.*, p.category_id, c.path AS category_path
                FROM attachments a
                JOIN projects p ON p.id = a.project_id
                JOIN categories c ON c.id = p.category_id
                WHERE a.id = ?
                """,
                (attachment_id,),
            ).fetchone()
            return dict(row) if row else None

    def delete_attachments_of_project(self, project_id: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM attachments WHERE project_id = ?", (project_id,))

    # ---------- period files ----------

    def upsert_period_file(
        self,
        category_id: int,
        period_type: str,
        period_label: str,
        relative_path: str,
        word_filename: str,
        project_count: int,
    ) -> dict[str, Any]:
        now = self._now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO period_files (
                    category_id, period_type, period_label, relative_path,
                    word_filename, project_count, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(category_id, period_type, period_label) DO UPDATE SET
                    relative_path = excluded.relative_path,
                    word_filename = excluded.word_filename,
                    project_count = excluded.project_count,
                    updated_at = excluded.updated_at
                """,
                (
                    category_id,
                    period_type,
                    period_label,
                    relative_path,
                    word_filename,
                    project_count,
                    now,
                ),
            )
            row = conn.execute(
                """
                SELECT * FROM period_files
                WHERE category_id = ? AND period_type = ? AND period_label = ?
                """,
                (category_id, period_type, period_label),
            ).fetchone()
            return dict(row)

    def save_period_file_version(
        self,
        *,
        category_id: int,
        period_type: str,
        period_label: str,
        relative_path: str,
        word_filename: str,
        project_count: int,
        md_content: str = "",
        file_content: Optional[bytes] = None,
        file_format: str = "md",
        file_sha256: str = "",
        source_sha256: str = "",
        source_snapshot_json: str = "",
        change_reason: str = "",
        force_new_version: bool = False,
    ) -> dict[str, Any]:
        """原子更新周期索引并保存 Markdown 历史版本。

        - ``md_content`` 为真源 Markdown 文本；``file_size`` 由
          ``len(md_content.encode('utf-8'))`` 推导。
        - ``file_content`` 仅作历史 docx 回滚备份（迁移期填，平时为 NULL）。
        - ``file_format`` 分发键：'md'（主流）/ 'docx'（迁移前/未迁）。
        """
        now = self._now()
        md_bytes = md_content.encode("utf-8")
        # 优先用 md 内容指纹；若只有 docx 备份（过渡期）则用其指纹。
        stored_sha256 = file_sha256 or hashlib.sha256(md_bytes).hexdigest()
        file_size = len(md_bytes)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO period_files (
                    category_id, period_type, period_label, relative_path,
                    word_filename, project_count, local_sync_status,
                    last_sync_error, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending', '', ?)
                ON CONFLICT(category_id, period_type, period_label) DO UPDATE SET
                    relative_path = excluded.relative_path,
                    word_filename = excluded.word_filename,
                    project_count = excluded.project_count,
                    local_sync_status = 'pending',
                    last_sync_error = '',
                    updated_at = excluded.updated_at
                """,
                (
                    category_id,
                    period_type,
                    period_label,
                    relative_path,
                    word_filename,
                    project_count,
                    now,
                ),
            )
            period_row = conn.execute(
                """
                SELECT * FROM period_files
                WHERE category_id = ? AND period_type = ? AND period_label = ?
                """,
                (category_id, period_type, period_label),
            ).fetchone()
            if not period_row:
                raise RuntimeError("保存周期文件索引失败")

            period_file_id = int(period_row["id"])
            current_version = None
            if period_row["current_version_id"]:
                current_version = conn.execute(
                    "SELECT * FROM period_file_versions WHERE id = ?",
                    (period_row["current_version_id"],),
                ).fetchone()

            created = True
            if (
                not force_new_version
                and current_version
                and current_version["source_sha256"] == source_sha256
            ):
                version_row = current_version
                created = False
            else:
                next_no = int(
                    conn.execute(
                        """
                        SELECT COALESCE(MAX(version_no), 0) + 1
                        FROM period_file_versions
                        WHERE period_file_id = ?
                        """,
                        (period_file_id,),
                    ).fetchone()[0]
                )
                cur = conn.execute(
                    """
                    INSERT INTO period_file_versions (
                        period_file_id, version_no, file_content, md_content,
                        file_format, file_size, file_sha256, source_sha256,
                        project_count, change_reason, source_snapshot_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        period_file_id,
                        next_no,
                        sqlite3.Binary(file_content) if file_content is not None else None,
                        md_content,
                        file_format,
                        file_size,
                        stored_sha256,
                        source_sha256,
                        project_count,
                        change_reason,
                        source_snapshot_json,
                        now,
                    ),
                )
                version_row = conn.execute(
                    "SELECT * FROM period_file_versions WHERE id = ?",
                    (cur.lastrowid,),
                ).fetchone()

            if not version_row:
                raise RuntimeError("保存 Word 历史版本失败")

            conn.execute(
                """
                UPDATE period_files SET
                    current_version_id = ?, current_sha256 = ?,
                    current_source_sha256 = ?, local_sync_status = 'pending',
                    last_sync_error = '', updated_at = ?
                WHERE id = ?
                """,
                (
                    version_row["id"],
                    version_row["file_sha256"],
                    version_row["source_sha256"],
                    now,
                    period_file_id,
                ),
            )
            refreshed = conn.execute(
                "SELECT * FROM period_files WHERE id = ?", (period_file_id,)
            ).fetchone()
            return {
                "period_file": dict(refreshed),
                "version": dict(version_row),
                "version_created": created,
            }

    def mark_period_file_sync(
        self,
        period_file_id: int,
        status: str,
        error: str = "",
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE period_files
                SET local_sync_status = ?, last_sync_error = ?
                WHERE id = ?
                """,
                (status, (error or "")[:1000], period_file_id),
            )

    def list_period_file_versions(self, period_file_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, period_file_id, version_no, file_size, file_sha256,
                       source_sha256, project_count, change_reason, created_at
                FROM period_file_versions
                WHERE period_file_id = ?
                ORDER BY version_no DESC
                """,
                (period_file_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_period_file_version(self, version_id: int) -> Optional[dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT v.*, pf.category_id, pf.period_type, pf.period_label,
                       pf.relative_path, pf.word_filename,
                       pf.current_version_id, c.name AS category_name,
                       c.path AS category_path
                FROM period_file_versions v
                JOIN period_files pf ON pf.id = v.period_file_id
                JOIN categories c ON c.id = pf.category_id
                WHERE v.id = ?
                """,
                (version_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_current_period_file_version(
        self, period_file_id: int
    ) -> Optional[dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT v.*
                FROM period_files pf
                JOIN period_file_versions v ON v.id = pf.current_version_id
                WHERE pf.id = ?
                """,
                (period_file_id,),
            ).fetchone()
            return dict(row) if row else None

    def restore_period_file_version(self, version_id: int) -> Optional[dict[str, Any]]:
        """复制历史版本为新的当前版本，保留一次完整的恢复审计记录。"""
        source = self.get_period_file_version(version_id)
        if not source:
            return None
        now = self._now()
        period_file_id = int(source["period_file_id"])
        with self.connect() as conn:
            next_no = int(
                conn.execute(
                    """
                    SELECT COALESCE(MAX(version_no), 0) + 1
                    FROM period_file_versions
                    WHERE period_file_id = ?
                    """,
                    (period_file_id,),
                ).fetchone()[0]
            )
            cur = conn.execute(
                """
                INSERT INTO period_file_versions (
                    period_file_id, version_no, file_content, md_content,
                    file_format, file_size, file_sha256, source_sha256,
                    project_count, change_reason, source_snapshot_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    period_file_id,
                    next_no,
                    sqlite3.Binary(source["file_content"])
                    if source.get("file_content") is not None else None,
                    source.get("md_content") or "",
                    source.get("file_format") or "docx",
                    source["file_size"],
                    source["file_sha256"],
                    source["source_sha256"],
                    source["project_count"],
                    f"恢复自版本 V{source['version_no']}",
                    source.get("source_snapshot_json") or "",
                    now,
                ),
            )
            restored = conn.execute(
                "SELECT * FROM period_file_versions WHERE id = ?",
                (cur.lastrowid,),
            ).fetchone()
            if not restored:
                raise RuntimeError("恢复 Word 历史版本失败")
            conn.execute(
                """
                UPDATE period_files SET
                    current_version_id = ?, current_sha256 = ?,
                    current_source_sha256 = ?, project_count = ?,
                    local_sync_status = 'pending', last_sync_error = '',
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    restored["id"],
                    restored["file_sha256"],
                    restored["source_sha256"],
                    restored["project_count"],
                    now,
                    period_file_id,
                ),
            )
            return dict(restored)

    def list_period_files(
        self,
        category_id: Optional[int] = None,
        period_type: Optional[str] = None,
        period_label: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT pf.*, c.name AS category_name, c.path AS category_path,
                   current_v.version_no AS current_version_no,
                   current_v.file_size AS current_file_size,
                   current_v.created_at AS current_version_created_at,
                   (SELECT COUNT(*) FROM period_file_versions pv
                    WHERE pv.period_file_id = pf.id) AS version_count
            FROM period_files pf
            JOIN categories c ON c.id = pf.category_id
            LEFT JOIN period_file_versions current_v
                   ON current_v.id = pf.current_version_id
            WHERE 1=1
        """
        params: list[Any] = []
        if category_id is not None:
            # 含子分类（中间级筛选）
            ids = self._category_and_descendant_ids(int(category_id))
            if not ids:
                return []
            placeholders = ",".join("?" * len(ids))
            sql += f" AND pf.category_id IN ({placeholders})"
            params.extend(ids)
        if period_type:
            sql += " AND pf.period_type = ?"
            params.append(period_type)
        if period_label:
            sql += " AND pf.period_label = ?"
            params.append(period_label)
        sql += " ORDER BY pf.updated_at DESC"
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            items: list[dict[str, Any]] = []
            for r in rows:
                d = dict(r)
                try:
                    d["category_path_names"] = self.get_category_path_names(d["category_id"])
                except Exception:
                    d["category_path_names"] = [d.get("category_name") or ""]
                items.append(d)
            return items

    def get_period_file(
        self, category_id: int, period_type: str, period_label: str
    ) -> Optional[dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT pf.*,
                       current_v.version_no AS current_version_no,
                       current_v.file_size AS current_file_size,
                       current_v.created_at AS current_version_created_at,
                       (SELECT COUNT(*) FROM period_file_versions pv
                        WHERE pv.period_file_id = pf.id) AS version_count
                FROM period_files pf
                LEFT JOIN period_file_versions current_v
                       ON current_v.id = pf.current_version_id
                WHERE pf.category_id = ? AND pf.period_type = ? AND pf.period_label = ?
                """,
                (category_id, period_type, period_label),
            ).fetchone()
            return dict(row) if row else None

    def get_period_file_by_id(self, period_file_id: int) -> Optional[dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT pf.*, c.name AS category_name, c.path AS category_path,
                       current_v.version_no AS current_version_no,
                       current_v.file_size AS current_file_size,
                       (SELECT COUNT(*) FROM period_file_versions pv
                        WHERE pv.period_file_id = pf.id) AS version_count
                FROM period_files pf
                JOIN categories c ON c.id = pf.category_id
                LEFT JOIN period_file_versions current_v
                       ON current_v.id = pf.current_version_id
                WHERE pf.id = ?
                """,
                (period_file_id,),
            ).fetchone()
            return dict(row) if row else None

    # ---------- 统计聚合（数据看板） ----------

    def count_saved_projects_period(self) -> dict[str, int]:
        """统计当期新增（仅 status='saved'）。

        口径：按 created_at 本地日期归窗，与存储（Database._now 本地时间）一致。
        - 当日：date(created_at) = date('now','localtime')
        - 当月：strftime('%Y-%m', created_at) = strftime('%Y-%m','now','localtime')
        - 当季：年份 + 季度序号 与当前一致
        返回 {'today': int, 'month': int, 'quarter': int}
        """
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE
                        WHEN date(created_at) = date('now', 'localtime')
                        THEN 1 ELSE 0 END) AS today,
                    SUM(CASE
                        WHEN strftime('%Y-%m', created_at)
                             = strftime('%Y-%m', 'now', 'localtime')
                        THEN 1 ELSE 0 END) AS month,
                    SUM(CASE
                        WHEN (strftime('%Y', created_at)
                              || '-Q'
                              || ((CAST(strftime('%m', created_at) AS INTEGER) - 1) / 3 + 1))
                             = (strftime('%Y', 'now', 'localtime')
                              || '-Q'
                              || ((CAST(strftime('%m', 'now', 'localtime') AS INTEGER) - 1) / 3 + 1))
                        THEN 1 ELSE 0 END) AS quarter
                FROM projects
                WHERE status = 'saved'
                """
            ).fetchone()
        return {
            "today": int(row["today"] or 0),
            "month": int(row["month"] or 0),
            "quarter": int(row["quarter"] or 0),
        }

    def project_daily_counts(self, days: int = 14) -> list[tuple[str, int]]:
        """最近 days 天每日新增（status='saved'）。

        返回 [(label 'MM-DD', count), ...] 按日期升序，无数据补 0。
        """
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS cnt
                FROM projects
                WHERE status = 'saved'
                GROUP BY day
                """
            ).fetchall()
        counts = {r["day"]: int(r["cnt"]) for r in rows}
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        result: list[tuple[str, int]] = []
        for offset in range(days - 1, -1, -1):
            day = today - timedelta(days=offset)
            full = day.strftime("%Y-%m-%d")
            label = day.strftime("%m-%d")
            result.append((label, counts.get(full, 0)))
        return result

    def project_monthly_counts(self, months: int = 6) -> list[tuple[str, int]]:
        """最近 months 月每月新增（status='saved'）。

        返回 [(label 'YYYY-MM', count), ...] 按月份升序，无数据补 0。
        """
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT strftime('%Y-%m', created_at) AS m, COUNT(*) AS cnt
                FROM projects
                WHERE status = 'saved'
                GROUP BY m
                """
            ).fetchall()
        counts = {r["m"]: int(r["cnt"]) for r in rows}
        now = datetime.now().replace(day=1)
        result: list[tuple[str, int]] = []
        for offset in range(months - 1, -1, -1):
            month_index = now.month - offset
            year = now.year
            while month_index <= 0:
                month_index += 12
                year -= 1
            while month_index > 12:
                month_index -= 12
                year += 1
            label = f"{year}-{month_index:02d}"
            result.append((label, counts.get(label, 0)))
        return result

    def project_quarterly_counts(self, quarters: int = 8) -> list[tuple[str, int]]:
        """最近 quarters 季每季新增（status='saved'）。

        返回 [(label 'YYYY-Qn', count), ...] 按季度升序，无数据补 0。
        标签由 path_utils.list_recent_quarters 统一产出，保证前后端一致。
        """
        from .path_utils import list_recent_quarters

        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT (strftime('%Y', created_at)
                        || '-Q'
                        || ((CAST(strftime('%m', created_at) AS INTEGER) - 1) / 3 + 1)
                       ) AS q, COUNT(*) AS cnt
                FROM projects
                WHERE status = 'saved'
                GROUP BY q
                """
            ).fetchall()
        counts = {r["q"]: int(r["cnt"]) for r in rows}
        result: list[tuple[str, int]] = []
        for (_year, _quarter, label) in list_recent_quarters(quarters):
            result.append((label, counts.get(label, 0)))
        return result

    # ---------- helpers ----------

    def _category_and_descendant_ids(self, category_id: int) -> list[int]:
        flat = self.list_categories_flat()
        children_map: dict[Optional[int], list[int]] = {}
        for c in flat:
            children_map.setdefault(c.get("parent_id"), []).append(c["id"])
        result: list[int] = []

        def walk(cid: int) -> None:
            result.append(cid)
            for child in children_map.get(cid, []):
                walk(child)

        walk(category_id)
        return result

    @staticmethod
    def _row_to_project(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        raw = data.pop("time_modes_json", "[]")
        try:
            data["time_modes"] = json.loads(raw) if raw else []
        except json.JSONDecodeError:
            data["time_modes"] = []
        return data
