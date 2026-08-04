"""本地文档管理系统 — FastAPI 入口（多级分类 + 项目 + 周期合并 Word）。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .database import Database
from .path_utils import (
    ensure_dir,
    get_iso_week_range,
    get_time_labels,
    sanitize_filename,
)
from .word_service import (
    WordFileLockedError,
    WordFileWriteError,
    assert_word_writable,
    build_period_word_document,
    html_to_plain_text,
    write_docx_bytes_atomic,
)

# ---------- 路径与配置 ----------

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT_DIR / "config.json"
FRONTEND_DIR = ROOT_DIR / "frontend"
# Vue 构建产物优先；兼容旧原生静态前端
FRONTEND_DIST_DIR = FRONTEND_DIR / "dist"
STATIC_DIR = (
    FRONTEND_DIST_DIR
    if (FRONTEND_DIST_DIR / "index.html").is_file()
    else FRONTEND_DIR
)


def load_config() -> dict:
    defaults = {
        "host": "127.0.0.1",
        "port": 8765,
        "data_dir": "data",
        "default_docs_root": "data/documents",
        "auto_open_browser": True,
        "autosave_seconds": 30,
        "db_backup_enabled": True,
        "db_backup_dir": "data/backups",
        "db_backup_interval_hours": 24,
        "db_backup_keep": 7,
    }
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
            defaults.update(user_cfg)
        except Exception:
            pass
    return defaults


CFG = load_config()
DATA_DIR = (ROOT_DIR / CFG["data_dir"]).resolve()
DEFAULT_DOCS_ROOT = (ROOT_DIR / CFG["default_docs_root"]).resolve()
DB_PATH = DATA_DIR / "app.db"

ensure_dir(DATA_DIR)
ensure_dir(DEFAULT_DOCS_ROOT)

db = Database(DB_PATH)


def resolve_backup_dir(raw_path: Optional[str] = None) -> Path:
    raw = (
        str(raw_path).strip()
        if raw_path is not None
        else str(CFG.get("db_backup_dir") or "data/backups").strip()
    )
    path = Path(raw or "data/backups").expanduser()
    if not path.is_absolute():
        path = ROOT_DIR / path
    return path.resolve()


def list_database_backup_paths() -> list[Path]:
    backup_dir = resolve_backup_dir()
    if not backup_dir.is_dir():
        return []
    return sorted(
        (item for item in backup_dir.glob("app_*.db") if item.is_file()),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )


def prune_database_backups() -> list[Path]:
    keep = max(1, int(CFG.get("db_backup_keep", 7) or 7))
    removed: list[Path] = []
    for stale in list_database_backup_paths()[keep:]:
        try:
            stale.unlink()
            removed.append(stale)
        except OSError:
            pass
    return removed


def backup_database_if_due(
    *,
    force: bool = False,
    raise_errors: bool = False,
) -> Optional[Path]:
    """按配置创建 SQLite 在线备份；失败不影响项目和 Word 主流程。"""
    if not force and not CFG.get("db_backup_enabled", True):
        return None
    backup_dir = ensure_dir(resolve_backup_dir())
    backups = list_database_backup_paths()
    interval_seconds = max(
        1,
        int(CFG.get("db_backup_interval_hours", 24) or 24),
    ) * 3600
    if (
        not force
        and backups
        and datetime.now().timestamp() - backups[0].stat().st_mtime < interval_seconds
    ):
        return None
    output = backup_dir / f"app_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.db"
    try:
        db.backup_to(output)
        prune_database_backups()
        return output
    except Exception as exc:
        if raise_errors:
            raise
        print(f"[backup] 数据库备份失败：{exc}")
        return None


def save_config() -> None:
    """原子保存当前配置，避免写入中断损坏 config.json。"""
    temp_path = CONFIG_PATH.with_name(CONFIG_PATH.name + ".writing.tmp")
    temp_path.write_text(
        json.dumps(CFG, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(CONFIG_PATH)

app = FastAPI(title="本地文档管理系统", version="2.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

backup_scheduler_task: Optional[asyncio.Task] = None


async def database_backup_scheduler() -> None:
    """每分钟检查一次是否达到自动备份间隔。"""
    while True:
        await asyncio.sleep(60)
        if CFG.get("db_backup_enabled", True):
            await asyncio.to_thread(backup_database_if_due)


@app.on_event("startup")
async def start_database_backup_scheduler() -> None:
    global backup_scheduler_task
    if backup_scheduler_task is None or backup_scheduler_task.done():
        backup_scheduler_task = asyncio.create_task(database_backup_scheduler())


@app.on_event("shutdown")
async def stop_database_backup_scheduler() -> None:
    global backup_scheduler_task
    if backup_scheduler_task and not backup_scheduler_task.done():
        backup_scheduler_task.cancel()
        try:
            await backup_scheduler_task
        except asyncio.CancelledError:
            pass
    backup_scheduler_task = None


# ---------- 数据模型 ----------


class CategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    path: str = ""
    description: str = ""
    parent_id: Optional[int] = None


class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    path: Optional[str] = None
    description: Optional[str] = None
    parent_id: Optional[int] = None


class ProjectDraftSave(BaseModel):
    """定时自动保存草稿。"""
    project_id: Optional[int] = None
    title: str = ""
    category_id: Optional[int] = None
    content: str = ""
    time_modes: list[str] = Field(default_factory=lambda: ["week", "month", "quarter"])


class DatabaseBackupSettingsUpdate(BaseModel):
    enabled: bool = True
    directory: str = Field(..., min_length=1, max_length=1000)
    interval_hours: int = Field(..., ge=1, le=8760)
    max_backups: int = Field(..., ge=1, le=1000)


# ---------- 工具函数 ----------


def resolve_path(raw_path: str) -> Path:
    p = Path(raw_path)
    if not p.is_absolute():
        p = (ROOT_DIR / p).resolve()
    else:
        p = p.resolve()
    return p


def resolve_category_path(raw_path: str) -> Path:
    return resolve_path(raw_path)


def enrich_category(item: dict) -> dict:
    try:
        p = resolve_category_path(item.get("path") or "")
        item["path_exists"] = p.exists() if item.get("path") else False
        item["resolved_path"] = str(p) if item.get("path") else ""
    except Exception:
        item["path_exists"] = False
        item["resolved_path"] = item.get("path") or ""
    item["path_names"] = db.get_category_path_names(item["id"])
    item["path_label"] = " / ".join(item["path_names"])
    return item


def ensure_project_category(category_id: int, *, require_path: bool = True) -> dict:
    """
    校验项目可归属的分类。
    支持选择中间级分类；若 require_path=True（正式保存），该分类须已设置本地目录。
    """
    cat = db.get_category(category_id)
    if not cat:
        raise HTTPException(404, "分类不存在")
    if require_path and not (cat.get("path") or "").strip():
        raise HTTPException(
            400,
            "该分类尚未设置本地目录，请先在分类管理中配置路径后再保存项目",
        )
    return cat


def ensure_leaf_category(category_id: int) -> dict:
    """兼容旧调用名：现允许中间级，仅强制本地目录。"""
    return ensure_project_category(category_id, require_path=True)


def default_category_path(name: str, parent_id: Optional[int]) -> str:
    if parent_id:
        parent = db.get_category(parent_id)
        if parent and parent.get("path"):
            return str(Path(parent["path"]) / sanitize_filename(name))
        # 沿路径名拼接
        names = db.get_category_path_names(parent_id) + [name]
        return str(DEFAULT_DOCS_ROOT.joinpath(*[sanitize_filename(n) for n in names]))
    return str(DEFAULT_DOCS_ROOT / sanitize_filename(name))


def period_word_path(category: dict, period_type: str, period_label: str) -> Path:
    """计算某叶子分类 + 周期对应的 Word 绝对路径。"""
    cat_path = resolve_category_path(category.get("path") or "")
    labels_map = {
        "week": "by_week",
        "month": "by_month",
        "quarter": "by_quarter",
    }
    folder = labels_map[period_type]
    filename = (
        f"{sanitize_filename(category['name'])}_{period_type}_{period_label}.docx"
    )
    return cat_path / folder / period_label / filename


def collect_period_targets(
    category_id: int,
    modes: list[str],
    labels: dict,
    old_project: Optional[dict] = None,
) -> list[tuple[int, str, str, Path]]:
    """
    收集本次保存需要写入/重建的周期文件。
    返回 [(category_id, period_type, period_label, abs_path), ...]
    """
    cat = db.get_category(category_id)
    if not cat:
        return []

    pairs: list[tuple[int, str, str]] = []
    if old_project:
        for ptype, lab in [
            ("week", old_project.get("week_label")),
            ("month", old_project.get("month_label")),
            ("quarter", old_project.get("quarter_label")),
        ]:
            if lab:
                pairs.append((old_project["category_id"], ptype, lab))

    for ptype in modes:
        lab = None
        if ptype == "week":
            lab = labels.get("week")
        elif ptype == "month":
            lab = labels.get("month")
        elif ptype == "quarter":
            lab = labels.get("quarter")
        if lab:
            pairs.append((category_id, ptype, lab))

    # 去重保持顺序
    seen: set[tuple[int, str, str]] = set()
    targets: list[tuple[int, str, str, Path]] = []
    for cid, ptype, lab in pairs:
        key = (cid, ptype, lab)
        if key in seen:
            continue
        seen.add(key)
        c = db.get_category(cid)
        if not c:
            continue
        targets.append((cid, ptype, lab, period_word_path(c, ptype, lab)))
    return targets


def precheck_period_files_writable(targets: list[tuple[int, str, str, Path]]) -> None:
    """
    写入前检查所有目标 Word 是否可写。
    任一文件被 Word/WPS 打开时，提前失败，避免半成功重复入库。
    """
    locked: list[str] = []
    for _cid, ptype, lab, path in targets:
        try:
            assert_word_writable(path)
        except WordFileLockedError:
            locked.append(f"{ptype}/{lab} → {path}")
    if locked:
        detail = "；".join(locked)
        raise HTTPException(
            status_code=423,
            detail=(
                "目标 Word 文件正在被打开，无法保存。"
                "请先关闭 Microsoft Word / WPS 中对应文件后重试。"
                f" 占用文件：{detail}"
            ),
        )


def friendly_word_http_error(exc: Exception) -> HTTPException:
    """将 Word 写入异常转为明确的 HTTP 错误。"""
    if isinstance(exc, WordFileLockedError):
        return HTTPException(
            status_code=423,
            detail=(
                "目标 Word 文件正在被打开，无法写入。"
                "请先关闭 Microsoft Word / WPS 中的该文件后再保存。"
                f" 文件：{exc.path}"
            ),
        )
    if isinstance(exc, WordFileWriteError):
        return HTTPException(
            status_code=500,
            detail=f"写入 Word 失败：{exc.path}。原因：{exc.cause or exc}",
        )
    # PermissionError 兜底
    if isinstance(exc, PermissionError):
        return HTTPException(
            status_code=423,
            detail=(
                "没有写入权限，或 Word 文件正被占用。"
                "请关闭相关 Word/WPS 文件后重试。"
            ),
        )
    if isinstance(exc, OSError) and getattr(exc, "winerror", None) == 32:
        return HTTPException(
            status_code=423,
            detail="文件正被其他程序占用（通常是 Word 已打开）。请关闭后重试。",
        )
    return HTTPException(status_code=500, detail=f"保存失败：{exc}")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_period_source_snapshot(
    *,
    category_path_names: list[str],
    period_type: str,
    period_label: str,
    projects: list[dict],
) -> tuple[str, str]:
    """生成可审计、可稳定比较的 Word 数据来源快照。"""
    snapshot_projects = []
    for project in projects:
        snapshot_projects.append(
            {
                "id": project.get("id"),
                "title": project.get("title") or "",
                "content": project.get("content") or "",
                "created_at": project.get("created_at") or "",
                "updated_at": project.get("updated_at") or "",
                "attachments": [
                    {
                        "id": att.get("id"),
                        "original_name": att.get("original_name") or "",
                        "stored_name": att.get("stored_name") or "",
                        "relative_path": att.get("relative_path") or "",
                    }
                    for att in (project.get("attachments") or [])
                ],
            }
        )
    snapshot = {
        "category_path_names": category_path_names,
        "period_type": period_type,
        "period_label": period_label,
        "projects": snapshot_projects,
    }
    raw = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return raw, _sha256(raw.encode("utf-8"))


def rebuild_period_word(
    category_id: int,
    period_type: str,
    period_label: str,
    change_reason: str = "项目数据更新",
) -> Optional[dict]:
    """生成新 Word 版本入库，并把该版本同步为本地最新文件。"""
    cat = db.get_category(category_id)
    if not cat:
        return None
    cat_path = resolve_category_path(cat.get("path") or "")
    ensure_dir(cat_path)

    labels_map = {
        "week": ("by_week", period_label),
        "month": ("by_month", period_label),
        "quarter": ("by_quarter", period_label),
    }
    if period_type not in labels_map:
        return None
    folder, label = labels_map[period_type]
    dest_dir = ensure_dir(cat_path / folder / label)
    filename = f"{sanitize_filename(cat['name'])}_{period_type}_{label}.docx"
    output = dest_dir / filename

    projects = db.list_projects_for_period(category_id, period_type, period_label)
    path_names = db.get_category_path_names(category_id)
    existing_period_file = db.get_period_file(category_id, period_type, period_label)
    if existing_period_file and output.is_file():
        current_version = db.get_current_period_file_version(
            int(existing_period_file["id"])
        )
        if not current_version:
            _archive_local_period_file(
                existing_period_file,
                output,
                change_reason="生成新版本前收录现有本地文件",
            )
        elif (
            existing_period_file.get("local_sync_status") == "synced"
            and _sha256(output.read_bytes()) != current_version["file_sha256"]
        ):
            _archive_local_period_file(
                existing_period_file,
                output,
                change_reason="生成新版本前收录本地 Word 手工修改",
            )
    assert_word_writable(output)
    try:
        file_content = build_period_word_document(
            category_path_names=path_names,
            period_type=period_type,
            period_label=period_label,
            projects=projects,
        )
    except (WordFileLockedError, WordFileWriteError):
        raise
    snapshot_json, source_sha256 = build_period_source_snapshot(
        category_path_names=path_names,
        period_type=period_type,
        period_label=period_label,
        projects=projects,
    )
    rel = str(Path(folder) / label / filename).replace("\\", "/")
    saved = db.save_period_file_version(
        category_id=category_id,
        period_type=period_type,
        period_label=period_label,
        relative_path=rel,
        word_filename=filename,
        project_count=len(projects),
        file_content=file_content,
        file_sha256=_sha256(file_content),
        source_sha256=source_sha256,
        source_snapshot_json=snapshot_json,
        change_reason=change_reason,
    )
    period_file = saved["period_file"]
    version = saved["version"]
    if saved["version_created"]:
        backup_database_if_due()
    # 若数据源没有变化，使用数据库中既有版本字节，避免无意义的二进制漂移。
    stored_content = bytes(version["file_content"])
    try:
        write_docx_bytes_atomic(stored_content, output)
        db.mark_period_file_sync(period_file["id"], "synced")
    except Exception as exc:
        db.mark_period_file_sync(period_file["id"], "error", str(exc))
        raise
    result = db.get_period_file(category_id, period_type, period_label) or period_file
    result["version_created"] = bool(saved["version_created"])
    return result


def _period_file_path(period_file: dict) -> Path:
    category = db.get_category(int(period_file["category_id"]))
    if not category:
        raise HTTPException(404, "分类不存在")
    return resolve_category_path(category.get("path") or "") / period_file["relative_path"]


def _archive_local_period_file(
    period_file: dict,
    file_path: Path,
    *,
    change_reason: str,
    create_backup: bool = True,
) -> dict:
    """把旧系统文件或检测到的本地手工改动收录为新的数据库版本。"""
    content = file_path.read_bytes()
    category_id = int(period_file["category_id"])
    projects = db.list_projects_for_period(
        category_id,
        period_file["period_type"],
        period_file["period_label"],
    )
    path_names = db.get_category_path_names(category_id)
    snapshot_json, _ = build_period_source_snapshot(
        category_path_names=path_names,
        period_type=period_file["period_type"],
        period_label=period_file["period_label"],
        projects=projects,
    )
    file_sha256 = _sha256(content)
    snapshot = json.loads(snapshot_json)
    snapshot["archived_local_file_sha256"] = file_sha256
    snapshot["archive_reason"] = change_reason
    snapshot_json = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    # 本地手工文件与按项目生成的文件必须拥有不同来源指纹，
    # 否则紧接着的自动重建会被误判为重复版本。
    source_sha256 = _sha256(snapshot_json.encode("utf-8"))
    saved = db.save_period_file_version(
        category_id=category_id,
        period_type=period_file["period_type"],
        period_label=period_file["period_label"],
        relative_path=period_file["relative_path"],
        word_filename=period_file["word_filename"],
        project_count=len(projects),
        file_content=content,
        file_sha256=file_sha256,
        source_sha256=source_sha256,
        source_snapshot_json=snapshot_json,
        change_reason=change_reason,
        force_new_version=True,
    )
    if create_backup:
        backup_database_if_due()
    db.mark_period_file_sync(saved["period_file"]["id"], "synced")
    return db.get_period_file(
        category_id,
        period_file["period_type"],
        period_file["period_label"],
    ) or saved["period_file"]


def ensure_period_file_local(period_file: dict) -> tuple[dict, Path]:
    """确保本地文件与数据库当前版本一致；缺失时直接从 BLOB 恢复。"""
    file_path = _period_file_path(period_file)
    current = db.get_current_period_file_version(int(period_file["id"]))

    if not current:
        if file_path.exists():
            period_file = _archive_local_period_file(
                period_file,
                file_path,
                change_reason="升级时收录现有本地文件",
            )
            return period_file, file_path
        rebuilt = rebuild_period_word(
            int(period_file["category_id"]),
            period_file["period_type"],
            period_file["period_label"],
            change_reason="本地与数据库均缺失时重建",
        )
        if not rebuilt:
            raise HTTPException(404, "周期文件不存在")
        return rebuilt, _period_file_path(rebuilt)

    current_content = bytes(current["file_content"])
    if file_path.exists():
        local_hash = _sha256(file_path.read_bytes())
        if local_hash == current["file_sha256"]:
            db.mark_period_file_sync(int(period_file["id"]), "synced")
            return period_file, file_path
        if period_file.get("local_sync_status") == "synced":
            # 已同步后内容再次变化，视为用户在 Word/WPS 中手工修改。
            period_file = _archive_local_period_file(
                period_file,
                file_path,
                change_reason="检测到本地 Word 手工修改",
            )
            return period_file, file_path

    try:
        write_docx_bytes_atomic(current_content, file_path)
        db.mark_period_file_sync(int(period_file["id"]), "synced")
    except Exception as exc:
        db.mark_period_file_sync(int(period_file["id"]), "error", str(exc))
        raise
    return period_file, file_path


def rebuild_project_periods(project: dict, modes: Optional[list[str]] = None) -> list[dict]:
    """根据项目的时间标签，重建对应周期 Word。"""
    modes = modes if modes is not None else (project.get("time_modes") or [])
    results = []
    mapping = [
        ("week", project.get("week_label")),
        ("month", project.get("month_label")),
        ("quarter", project.get("quarter_label")),
    ]
    for ptype, label in mapping:
        if ptype in modes and label:
            pf = rebuild_period_word(project["category_id"], ptype, label)
            if pf:
                results.append(pf)
    return results


def store_project_attachments(
    project_id: int,
    category: dict,
    uploads: list[UploadFile],
) -> list[dict]:
    cat_path = resolve_category_path(category.get("path") or "")
    ensure_dir(cat_path)
    att_dir = ensure_dir(cat_path / "attachments" / f"project_{project_id}")
    labels = get_time_labels()
    records = []
    for uf in uploads:
        if not uf or not uf.filename:
            continue
        # read bytes — caller must await; this helper is sync so receive bytes outside
        pass
    return records


def seed_default_categories() -> None:
    existing = db.list_categories_flat()
    if existing:
        return
    defaults = [
        ("工作", "", "工作相关"),
        ("学习", "", "学习相关"),
        ("个人", "", "个人记录"),
    ]
    root_ids = {}
    for name, path, desc in defaults:
        try:
            cat = db.create_category(name=name, path="", description=desc, parent_id=None)
            root_ids[name] = cat["id"]
        except Exception:
            pass

    leaves = [
        ("工作", "日常纪要", "日常工作项目"),
        ("工作", "会议项目", "会议相关项目"),
        ("学习", "阅读笔记", "阅读与学习项目"),
        ("个人", "灵感草稿", "灵感与草稿"),
    ]
    for root_name, leaf_name, desc in leaves:
        parent_id = root_ids.get(root_name)
        if not parent_id:
            continue
        path = default_category_path(leaf_name, parent_id)
        ensure_dir(Path(path))
        try:
            db.create_category(
                name=leaf_name,
                path=path,
                description=desc,
                parent_id=parent_id,
            )
        except Exception:
            pass


def backfill_existing_period_file_versions() -> int:
    """升级时将已有本地 Word 原样收录为 V1，不重建、不改写文件。"""
    archived = 0
    for period_file in db.list_period_files():
        if period_file.get("current_version_id"):
            continue
        try:
            file_path = _period_file_path(period_file)
            if not file_path.is_file():
                continue
            _archive_local_period_file(
                period_file,
                file_path,
                change_reason="升级时收录现有本地文件",
                create_backup=False,
            )
            archived += 1
        except Exception as exc:
            print(
                f"[word-version] 收录现有文件失败："
                f"{period_file.get('word_filename') or period_file.get('id')}：{exc}"
            )
    return archived


seed_default_categories()
backfilled_versions = backfill_existing_period_file_versions()
backup_database_if_due(force=backfilled_versions > 0)


# ---------- API：系统 ----------


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "app": "本地文档管理系统",
        "version": "2.1.0",
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "root": str(ROOT_DIR),
        "data_dir": str(DATA_DIR),
    }


@app.get("/api/config")
def get_config():
    labels = get_time_labels()
    week = get_iso_week_range()
    return {
        "default_docs_root": str(DEFAULT_DOCS_ROOT),
        "data_dir": str(DATA_DIR),
        "host": CFG["host"],
        "port": CFG["port"],
        "autosave_seconds": int(CFG.get("autosave_seconds", 30)),
        "db_backup": {
            "enabled": bool(CFG.get("db_backup_enabled", True)),
            "interval_hours": int(CFG.get("db_backup_interval_hours", 24)),
            "keep": int(CFG.get("db_backup_keep", 7)),
            "directory": str(resolve_backup_dir()),
        },
        "week_rule": {
            "standard": "ISO 8601",
            "start_day_cn": "周一",
            "end_day_cn": "周日",
            "description": "按 ISO 周计算：周一到周日",
            "current_week_label": labels["week"],
            "current_week_start": labels["week_start"],
            "current_week_end": labels["week_end"],
            "current_month": labels["month"],
            "current_quarter": labels["quarter"],
            "iso_year": week["iso_year"],
            "iso_week": week["iso_week"],
        },
    }


@app.get("/api/time-info")
def get_time_info():
    labels = get_time_labels()
    week = get_iso_week_range()
    return {
        "labels": labels,
        "week": {
            "standard": "ISO 8601",
            "start_day_cn": "周一",
            "end_day_cn": "周日",
            "label": week["week_label"],
            "start": week["week_start_str"],
            "end": week["week_end_str"],
            "range_display": week["week_range_display"],
            "iso_year": week["iso_year"],
            "iso_week": week["iso_week"],
        },
        "autosave_seconds": int(CFG.get("autosave_seconds", 30)),
    }


def _backup_file_info(path: Path) -> dict:
    stat = path.stat()
    return {
        "filename": path.name,
        "path": str(path),
        "size": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime).strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
    }


def _database_backup_settings_payload() -> dict:
    backups = list_database_backup_paths()
    db_stat = DB_PATH.stat() if DB_PATH.exists() else None
    return {
        "settings": {
            "enabled": bool(CFG.get("db_backup_enabled", True)),
            "directory": str(CFG.get("db_backup_dir") or "data/backups"),
            "resolved_directory": str(resolve_backup_dir()),
            "interval_hours": int(CFG.get("db_backup_interval_hours", 24)),
            "max_backups": int(CFG.get("db_backup_keep", 7)),
        },
        "database": {
            "path": str(DB_PATH),
            "size": db_stat.st_size if db_stat else 0,
            "modified_at": (
                datetime.fromtimestamp(db_stat.st_mtime).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                if db_stat
                else ""
            ),
        },
        "summary": {
            "backup_count": len(backups),
            "total_size": sum(item.stat().st_size for item in backups),
            "latest_backup_at": (
                datetime.fromtimestamp(backups[0].stat().st_mtime).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                if backups
                else ""
            ),
        },
    }


def _resolve_backup_file(filename: str) -> Path:
    safe_name = Path(filename).name
    if (
        safe_name != filename
        or not safe_name.startswith("app_")
        or Path(safe_name).suffix.lower() != ".db"
    ):
        raise HTTPException(400, "备份文件名无效")
    backup_dir = resolve_backup_dir()
    candidate = (backup_dir / safe_name).resolve()
    if candidate.parent != backup_dir.resolve():
        raise HTTPException(400, "备份文件路径无效")
    if not candidate.is_file():
        raise HTTPException(404, "数据库备份不存在")
    return candidate


@app.get("/api/settings/database-backup")
def get_database_backup_settings():
    return _database_backup_settings_payload()


@app.put("/api/settings/database-backup")
def update_database_backup_settings(body: DatabaseBackupSettingsUpdate):
    directory = body.directory.strip()
    try:
        resolved_directory = ensure_dir(resolve_backup_dir(directory))
    except Exception as exc:
        raise HTTPException(400, f"备份目录不可用：{exc}")

    previous = dict(CFG)
    CFG.update(
        {
            "db_backup_enabled": body.enabled,
            "db_backup_dir": directory,
            "db_backup_interval_hours": body.interval_hours,
            "db_backup_keep": body.max_backups,
        }
    )
    try:
        save_config()
        removed = prune_database_backups()
    except Exception as exc:
        CFG.clear()
        CFG.update(previous)
        raise HTTPException(500, f"保存备份设置失败：{exc}")
    payload = _database_backup_settings_payload()
    payload["settings"]["resolved_directory"] = str(resolved_directory)
    payload["removed_count"] = len(removed)
    return payload


@app.get("/api/database-backups")
def list_database_backups():
    items = [_backup_file_info(path) for path in list_database_backup_paths()]
    return {"items": items, "total": len(items)}


@app.post("/api/database-backups")
def create_database_backup():
    try:
        output = backup_database_if_due(force=True, raise_errors=True)
    except Exception as exc:
        raise HTTPException(500, f"创建数据库备份失败：{exc}")
    if not output:
        raise HTTPException(500, "创建数据库备份失败")
    return {"ok": True, "backup": _backup_file_info(output)}


@app.get("/api/database-backups/{filename}/download")
def download_database_backup(filename: str):
    path = _resolve_backup_file(filename)
    encoded = quote(path.name)
    return FileResponse(
        path=str(path),
        filename=path.name,
        media_type="application/vnd.sqlite3",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"},
    )


@app.delete("/api/database-backups/{filename}")
def delete_database_backup(filename: str):
    path = _resolve_backup_file(filename)
    try:
        path.unlink()
    except OSError as exc:
        raise HTTPException(500, f"删除数据库备份失败：{exc}")
    return {"ok": True, "deleted": path.name}


@app.post("/api/database-backups/open-folder")
def open_database_backup_folder():
    import os
    import subprocess
    import sys

    path = ensure_dir(resolve_backup_dir())
    try:
        if sys.platform == "win32":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as exc:
        raise HTTPException(500, f"打开备份目录失败：{exc}")
    return {"ok": True, "path": str(path)}


@app.post("/api/browse-folder")
def browse_folder(initial_path: Optional[str] = None, purpose: str = "category"):
    import subprocess
    import sys

    start_dir = str(resolve_backup_dir() if purpose == "backup" else DEFAULT_DOCS_ROOT)
    dialog_title = "请选择数据库备份目录" if purpose == "backup" else "请选择分类对应的本地目录"
    if initial_path:
        try:
            p = resolve_category_path(initial_path)
            if p.exists():
                start_dir = str(p if p.is_dir() else p.parent)
            elif p.parent.exists():
                start_dir = str(p.parent)
        except Exception:
            pass

    try:
        if sys.platform == "win32":
            safe_start = start_dir.replace("'", "''")
            ps = (
                "Add-Type -AssemblyName System.Windows.Forms; "
                "$f = New-Object System.Windows.Forms.FolderBrowserDialog; "
                f"$f.Description = '{dialog_title}'; "
                "$f.ShowNewFolderButton = $true; "
                f"$f.SelectedPath = '{safe_start}'; "
                "if ($f.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) "
                "{ [Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
                "Write-Output $f.SelectedPath } "
                "else { Write-Output '' }"
            )
            completed = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-STA",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    ps,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=300,
            )
            selected = (completed.stdout or "").strip()
            if completed.returncode != 0 and not selected:
                err = (completed.stderr or "").strip() or "对话框打开失败"
                raise HTTPException(500, f"选择目录失败：{err}")
            if not selected:
                return {"ok": False, "cancelled": True, "path": ""}
            return {"ok": True, "cancelled": False, "path": selected}

        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askdirectory(
            title=dialog_title,
            initialdir=start_dir or None,
        )
        root.destroy()
        if not selected:
            return {"ok": False, "cancelled": True, "path": ""}
        return {"ok": True, "cancelled": False, "path": selected}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"选择目录失败：{e}")


# ---------- API：分类树 ----------


@app.get("/api/categories")
def list_categories(tree: bool = False, leaves_only: bool = False):
    if tree:
        nodes = db.get_category_tree()

        def walk(n):
            enrich_category(n)
            for ch in n.get("children") or []:
                walk(ch)

        for r in nodes:
            walk(r)
        return {"items": nodes, "mode": "tree"}

    items = db.list_categories_flat()
    if leaves_only:
        items = [c for c in items if c.get("is_leaf")]
    items = [enrich_category(c) for c in items]
    return {"items": items, "mode": "flat"}


@app.post("/api/categories")
def create_category(body: CategoryCreate):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "分类名称不能为空")

    parent_id = body.parent_id
    path = (body.path or "").strip()

    # 叶子（无 path 时自动生成）；父级可无 path
    # 规则：若用户提供 path 则用；否则若可能作为叶子（默认），自动生成
    if not path:
        # 只有创建时临时给路径；父级后续可清空。这里默认总给路径，便于直接挂项目
        path = default_category_path(name, parent_id)

    try:
        abs_path = resolve_category_path(path) if path else None
        if abs_path:
            ensure_dir(abs_path)
            path = str(abs_path)
        item = db.create_category(
            name=name,
            path=path or "",
            description=body.description or "",
            parent_id=parent_id,
        )
        return enrich_category(item)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f"创建失败：{e}")


@app.put("/api/categories/{category_id}")
def update_category(category_id: int, body: CategoryUpdate):
    current = db.get_category(category_id)
    if not current:
        raise HTTPException(404, "分类不存在")

    new_path = body.path
    if new_path is not None:
        new_path = new_path.strip()
        if new_path:
            abs_path = resolve_category_path(new_path)
            ensure_dir(abs_path)
            new_path = str(abs_path)

    try:
        # parent_id: 若 body 未传则保持；传 null 表示移到根
        parent_arg = ...
        data = body.model_dump(exclude_unset=True)
        if "parent_id" in data:
            parent_arg = data["parent_id"]

        item = db.update_category(
            category_id,
            name=body.name,
            path=new_path if new_path is not None else None,
            description=body.description,
            parent_id=parent_arg,
        )
        if not item:
            raise HTTPException(404, "分类不存在")
        return enrich_category(item)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"更新失败：{e}")


@app.delete("/api/categories/{category_id}")
def delete_category(category_id: int, delete_files: bool = False):
    current = db.get_category(category_id)
    if not current:
        raise HTTPException(404, "分类不存在")
    if int(current.get("child_count") or 0) > 0:
        raise HTTPException(400, "请先删除子分类，再删除本分类")
    if int(current.get("project_count") or 0) > 0:
        # 仍允许删除（级联项目），但前端会二次确认
        pass

    ok = db.delete_category(category_id)
    if not ok:
        raise HTTPException(404, "分类不存在")

    if delete_files and current.get("path"):
        try:
            p = resolve_category_path(current["path"])
            if p.exists() and (DEFAULT_DOCS_ROOT in p.parents or p == DEFAULT_DOCS_ROOT):
                shutil.rmtree(p, ignore_errors=True)
        except Exception:
            pass
    return {"ok": True, "deleted_id": category_id}


@app.post("/api/categories/{category_id}/open-folder")
def open_category_folder(category_id: int):
    import os
    import subprocess
    import sys

    cat = db.get_category(category_id)
    if not cat:
        raise HTTPException(404, "分类不存在")
    raw = cat.get("path") or ""
    if not raw:
        raise HTTPException(400, "该分类尚未设置本地目录")
    path = resolve_category_path(raw)
    ensure_dir(path)
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", str(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as e:
        raise HTTPException(500, f"打开文件夹失败：{e}")
    return {"ok": True, "path": str(path)}


# ---------- API：项目 ----------


@app.get("/api/projects")
def list_projects(
    category_id: Optional[int] = None,
    keyword: Optional[str] = None,
    include_draft: bool = False,
):
    items = db.list_projects(
        category_id=category_id,
        keyword=keyword,
        include_draft=include_draft,
    )
    return {"items": items, "total": len(items)}


@app.get("/api/projects/{project_id}")
def get_project(project_id: int):
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(404, "项目不存在")
    return project


@app.post("/api/projects")
async def save_project(
    content: str = Form(...),
    category_id: int = Form(...),
    title: str = Form(""),
    time_modes: str = Form("week,month,quarter"),
    project_id: Optional[int] = Form(None),
    client_save_token: str = Form(""),
    files: list[UploadFile] = File(default=[]),
):
    """
    正式保存项目：
    - 项目归属叶子分类
    - 按勾选的周/月/季，把该分类本周期所有项目写入同一 Word
    - Word 被占用时返回明确错误，且不创建重复项目
    """
    content = (content or "").strip()
    plain_content = html_to_plain_text(content).strip()
    if not plain_content:
        raise HTTPException(400, "项目内容不能为空")

    cat = ensure_leaf_category(category_id)
    modes = [m.strip() for m in (time_modes or "").split(",") if m.strip()]
    if not modes:
        modes = ["month"]

    now = datetime.now()
    labels = get_time_labels(now)
    week_label = labels["week"] if "week" in modes else None
    month_label = labels["month"] if "month" in modes else None
    quarter_label = labels["quarter"] if "quarter" in modes else None

    clean_title = (title or "").strip()
    if not clean_title:
        for line in plain_content.replace("\r\n", "\n").split("\n"):
            if line.strip():
                clean_title = line.strip()[:60]
                break
        if not clean_title:
            clean_title = f"项目_{labels['datetime']}"

    preview = plain_content[:200]

    # 解析要复用的项目：优先 project_id；否则用同一编辑会话的草稿/最近草稿
    old_project = db.get_project(project_id) if project_id else None
    if not old_project and client_save_token:
        # 同一浏览器会话 token 命中草稿/失败重试时，尽量复用
        # 简化：匹配同分类下同标题草稿
        drafts = [
            p
            for p in db.list_projects(category_id=category_id, include_draft=True, limit=50)
            if p.get("status") == "draft" and (p.get("title") or "") == clean_title
        ]
        if drafts:
            old_project = drafts[0]
            project_id = old_project["id"]

    # 关键：先检查全部目标 Word 可写，再动数据库（避免半成功重复入库）
    targets = collect_period_targets(
        category_id=category_id,
        modes=modes,
        labels={
            "week": week_label,
            "month": month_label,
            "quarter": quarter_label,
        },
        old_project=old_project,
    )
    try:
        precheck_period_files_writable(targets)
    except HTTPException:
        raise

    # 入库 / 更新（失败重试时带上同一 project_id，不会重复创建）
    if old_project:
        project = db.update_project(
            project_id=old_project["id"],
            title=clean_title,
            category_id=category_id,
            content=content,
            content_preview=preview,
            time_modes=modes,
            week_label=week_label,
            month_label=month_label,
            quarter_label=quarter_label,
            status="saved",
            clear_week="week" not in modes,
            clear_month="month" not in modes,
            clear_quarter="quarter" not in modes,
        )
    else:
        project = db.create_project(
            title=clean_title,
            category_id=category_id,
            content=content,
            content_preview=preview,
            time_modes=modes,
            week_label=week_label,
            month_label=month_label,
            quarter_label=quarter_label,
            status="saved",
        )

    if not project:
        raise HTTPException(500, "保存项目失败")

    # 附件
    cat_path = resolve_category_path(cat.get("path") or "")
    ensure_dir(cat_path)
    att_dir = ensure_dir(cat_path / "attachments" / f"project_{project['id']}")
    attachment_records = []
    for uf in files or []:
        if not uf or not uf.filename:
            continue
        raw = await uf.read()
        if not raw:
            continue
        original = Path(uf.filename).name
        safe = sanitize_filename(Path(original).stem)
        ext = Path(original).suffix
        stored = f"{safe}_{labels['datetime']}{ext}"
        dest = att_dir / stored
        i = 1
        while dest.exists():
            dest = att_dir / f"{safe}_{labels['datetime']}_{i}{ext}"
            i += 1
            stored = dest.name
        dest.write_bytes(raw)
        rel = str(dest.relative_to(cat_path)).replace("\\", "/")
        rec = db.add_attachment(
            project_id=project["id"],
            original_name=original,
            stored_name=stored,
            relative_path=rel,
            size=len(raw),
            content_type=uf.content_type or "",
        )
        attachment_records.append(rec)

    # 重建 Word；若中途锁定则给出明确错误（precheck 已挡主路径）
    period_files = []
    try:
        rebuild_set = {(cid, ptype, lab) for cid, ptype, lab, _ in targets}
        for cid, ptype, lab in sorted(rebuild_set):
            pf = rebuild_period_word(
                cid,
                ptype,
                lab,
                change_reason=f"保存项目 #{project['id']}",
            )
            if pf:
                period_files.append(pf)
    except (WordFileLockedError, WordFileWriteError, PermissionError, OSError) as e:
        # Word 写失败：项目数据已在库中（可继续编辑），但明确告知未写入 Word
        # 对新建场景：保持 project_id 返回给前端，避免用户再次点保存时再开新项目
        raise friendly_word_http_error(e)

    full = db.get_project(project["id"])
    full["period_files"] = period_files
    if attachment_records:
        full = db.get_project(project["id"])
        full["period_files"] = period_files
    # 总是回传 id，前端可挂在当前编辑会话，防止重复创建
    full["reused_existing"] = bool(old_project)
    return full


@app.post("/api/projects/autosave")
def autosave_project(body: ProjectDraftSave):
    """
    定时自动保存草稿（不写入 Word）。
    避免长时间粘贴编辑时内容丢失。
    """
    content = (body.content or "").strip()
    plain_content = html_to_plain_text(content).strip()
    if not plain_content and not (body.title or "").strip():
        return {"ok": False, "skipped": True, "reason": "empty"}

    title = (body.title or "").strip()
    if not title:
        for line in plain_content.replace("\r\n", "\n").split("\n"):
            if line.strip():
                title = line.strip()[:60]
                break
        if not title:
            title = f"草稿_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    modes = body.time_modes or ["week", "month", "quarter"]
    preview = plain_content[:200]

    # 草稿允许未选分类；有分类则必须是叶子
    category_id = body.category_id
    if category_id is not None:
        # 草稿允许中间级，不强制本地目录（正式保存时再校验路径）
        ensure_project_category(category_id, require_path=False)
    else:
        # 默认取第一个已有分类（优先叶子）
        leaves = db.list_leaf_categories()
        if leaves:
            category_id = leaves[0]["id"]
        else:
            flat = db.list_categories_flat()
            if not flat:
                raise HTTPException(400, "请先创建分类")
            category_id = flat[0]["id"]

    if body.project_id:
        existing = db.get_project(body.project_id)
        if existing:
            project = db.update_project(
                project_id=body.project_id,
                title=title,
                category_id=category_id,
                content=body.content or "",
                content_preview=preview,
                time_modes=modes,
                status="draft",
            )
            return {"ok": True, "project": project, "mode": "update"}

    project = db.create_project(
        title=title,
        category_id=category_id,
        content=body.content or "",
        content_preview=preview,
        time_modes=modes,
        week_label=None,
        month_label=None,
        quarter_label=None,
        status="draft",
    )
    return {"ok": True, "project": project, "mode": "create"}


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: int):
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(404, "项目不存在")

    # 记录需重建的周期
    rebuild_set: list[tuple[int, str, str]] = []
    for ptype, lab in [
        ("week", project.get("week_label")),
        ("month", project.get("month_label")),
        ("quarter", project.get("quarter_label")),
    ]:
        if lab:
            rebuild_set.append((project["category_id"], ptype, lab))

    # 删除附件文件
    cat_path = resolve_category_path(project.get("category_path") or "")
    for att in project.get("attachments") or []:
        try:
            ap = cat_path / att["relative_path"]
            if ap.exists() and ap.is_file():
                ap.unlink()
        except Exception:
            pass
    try:
        att_dir = cat_path / "attachments" / f"project_{project_id}"
        if att_dir.exists() and att_dir.is_dir():
            shutil.rmtree(att_dir, ignore_errors=True)
    except Exception:
        pass

    db.delete_project(project_id)

    # 重建剩余项目的周期 Word
    period_files = []
    for cid, ptype, lab in rebuild_set:
        pf = rebuild_period_word(
            cid,
            ptype,
            lab,
            change_reason=f"删除项目 #{project_id}",
        )
        if pf:
            period_files.append(pf)

    return {"ok": True, "deleted_id": project_id, "period_files": period_files}


@app.get("/api/projects/{project_id}/open")
@app.post("/api/projects/{project_id}/open")
def open_project_noop(project_id: int):
    """兼容：打开项目详情在前端完成。"""
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(404, "项目不存在")
    return project


@app.get("/api/attachments/{attachment_id}/download")
def download_attachment(attachment_id: int):
    att = db.get_attachment(attachment_id)
    if not att:
        raise HTTPException(404, "附件不存在")
    cat_path = resolve_category_path(att["category_path"])
    fp = cat_path / att["relative_path"]
    if not fp.exists():
        raise HTTPException(404, f"附件文件不存在：{fp}")
    filename = quote(att["original_name"])
    return FileResponse(
        path=str(fp),
        filename=att["original_name"],
        media_type=att.get("content_type") or "application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@app.get("/api/period-files")
def list_period_files(
    category_id: Optional[int] = None,
    period_type: Optional[str] = None,
    period_label: Optional[str] = None,
):
    items = db.list_period_files(
        category_id=category_id,
        period_type=period_type,
        period_label=period_label,
    )
    for it in items:
        try:
            cat_path = resolve_category_path(it.get("category_path") or "")
            fp = cat_path / it["relative_path"]
            it["abs_path"] = str(fp)
            it["exists"] = fp.exists()
        except Exception:
            it["abs_path"] = ""
            it["exists"] = False
        it["database_backed"] = bool(it.get("current_version_id"))
        # 补全全路径显示字段
        names = it.get("category_path_names") or []
        it["category_path_label"] = " / ".join([n for n in names if n]) or (it.get("category_name") or "")
    return {"items": items}


@app.post("/api/period-files/open")
def open_period_file(
    category_id: int = Form(...),
    period_type: str = Form(...),
    period_label: str = Form(...),
):
    import os
    import subprocess
    import sys

    pf = db.get_period_file(category_id, period_type, period_label)
    if not pf:
        # 尝试重建
        pf = rebuild_period_word(
            category_id,
            period_type,
            period_label,
            change_reason="首次打开时重建",
        )
    if not pf:
        raise HTTPException(404, "周期文件不存在")
    try:
        pf, fp = ensure_period_file_local(pf)
    except (WordFileLockedError, WordFileWriteError, PermissionError, OSError) as exc:
        raise friendly_word_http_error(exc)
    if not fp.exists():
        raise HTTPException(404, f"文件不存在：{fp}")
    try:
        if sys.platform == "win32":
            os.startfile(str(fp))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(fp)])
        else:
            subprocess.Popen(["xdg-open", str(fp)])
    except Exception as e:
        raise HTTPException(500, f"打开失败：{e}")
    return {"ok": True, "path": str(fp)}


@app.get("/api/period-files/download")
def download_period_file(
    category_id: int,
    period_type: str,
    period_label: str,
):
    pf = db.get_period_file(category_id, period_type, period_label)
    if not pf:
        pf = rebuild_period_word(
            category_id,
            period_type,
            period_label,
            change_reason="首次下载时重建",
        )
    if not pf:
        raise HTTPException(404, "周期文件不存在")
    try:
        pf, fp = ensure_period_file_local(pf)
    except (WordFileLockedError, WordFileWriteError, PermissionError, OSError) as exc:
        raise friendly_word_http_error(exc)
    if not fp.exists():
        raise HTTPException(404, f"文件不存在：{fp}")
    filename = quote(fp.name)
    return FileResponse(
        path=str(fp),
        filename=fp.name,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@app.get("/api/period-files/{period_file_id}/versions")
def list_period_file_versions(period_file_id: int):
    period_file = db.get_period_file_by_id(period_file_id)
    if not period_file:
        raise HTTPException(404, "周期文件不存在")
    try:
        ensure_period_file_local(period_file)
    except (WordFileLockedError, WordFileWriteError, PermissionError, OSError) as exc:
        raise friendly_word_http_error(exc)
    period_file = db.get_period_file_by_id(period_file_id) or period_file
    items = db.list_period_file_versions(period_file_id)
    current_id = period_file.get("current_version_id")
    for item in items:
        item["is_current"] = item["id"] == current_id
    return {"items": items, "period_file": period_file}


@app.get("/api/period-file-versions/{version_id}/download")
def download_period_file_version(version_id: int):
    version = db.get_period_file_version(version_id)
    if not version:
        raise HTTPException(404, "Word 历史版本不存在")
    stem = Path(version["word_filename"]).stem
    filename_raw = f"{stem}_V{version['version_no']}.docx"
    filename = quote(filename_raw)
    return Response(
        content=bytes(version["file_content"]),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@app.post("/api/period-file-versions/{version_id}/restore")
def restore_period_file_version(version_id: int):
    source = db.get_period_file_version(version_id)
    if not source:
        raise HTTPException(404, "Word 历史版本不存在")
    period_file = db.get_period_file_by_id(int(source["period_file_id"]))
    if not period_file:
        raise HTTPException(404, "周期文件不存在")
    output = _period_file_path(period_file)
    try:
        assert_word_writable(output)
        restored = db.restore_period_file_version(version_id)
        if not restored:
            raise HTTPException(404, "Word 历史版本不存在")
        backup_database_if_due()
        write_docx_bytes_atomic(bytes(restored["file_content"]), output)
        db.mark_period_file_sync(int(source["period_file_id"]), "synced")
    except HTTPException:
        raise
    except (WordFileLockedError, WordFileWriteError, PermissionError, OSError) as exc:
        db.mark_period_file_sync(int(source["period_file_id"]), "error", str(exc))
        raise friendly_word_http_error(exc)
    refreshed = db.get_period_file_by_id(int(source["period_file_id"]))
    return {
        "ok": True,
        "period_file": refreshed,
        "restored_version_no": restored["version_no"],
    }


# 兼容旧文档 API（避免前端 404），转为项目列表
@app.get("/api/documents")
def list_documents_compat(category_id: Optional[int] = None, keyword: Optional[str] = None):
    items = db.list_projects(category_id=category_id, keyword=keyword)
    # 适配旧字段名
    adapted = []
    for p in items:
        adapted.append(
            {
                "id": p["id"],
                "title": p["title"],
                "category_id": p["category_id"],
                "category_name": p.get("category_name"),
                "content_preview": p.get("content_preview"),
                "week_label": p.get("week_label"),
                "month_label": p.get("month_label"),
                "quarter_label": p.get("quarter_label"),
                "created_at": p.get("created_at"),
                "updated_at": p.get("updated_at"),
                "attachments": p.get("attachments") or [],
                "status": p.get("status"),
            }
        )
    return {"items": adapted, "total": len(adapted)}


# ---------- API：统计看板 ----------


class ProjectStatsSummary(BaseModel):
    """当期新增项目统计（仅 status='saved'）。"""

    today: int
    month: int
    quarter: int


class ProjectStatsTrend(BaseModel):
    """新增项目趋势（轴标签与数值一一对应，按时间升序）。"""

    range: str
    labels: list[str]
    values: list[int]


@app.get("/api/stats/projects-summary", response_model=ProjectStatsSummary)
def stats_projects_summary() -> ProjectStatsSummary:
    """统计当日 / 当月 / 当季新增（status='saved'）。"""
    return db.count_saved_projects_period()


@app.get("/api/stats/projects-trend", response_model=ProjectStatsTrend)
def stats_projects_trend(range: str = "day") -> ProjectStatsTrend:
    """按 range=day|month|quarter 返回新增项目趋势（无数据补 0）。

    range 非法值回退为 day。
    """
    if range == "month":
        rows = db.project_monthly_counts(6)
    elif range == "quarter":
        rows = db.project_quarterly_counts(8)
    else:
        range = "day"
        rows = db.project_daily_counts(14)
    return ProjectStatsTrend(
        range=range,
        labels=[r[0] for r in rows],
        values=[int(r[1]) for r in rows],
    )


# ---------- 静态前端 ----------

if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="frontend")


def run() -> None:
    import uvicorn

    host = CFG.get("host", "127.0.0.1")
    port = int(CFG.get("port", 8765))
    url = f"http://{host}:{port}"

    if CFG.get("auto_open_browser", True):
        try:
            webbrowser.open(url)
        except Exception:
            pass

    uvicorn.run(
        "backend.main:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    run()
