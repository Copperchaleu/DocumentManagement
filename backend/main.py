"""本地文档管理系统 — FastAPI 入口（多级分类 + 项目 + 周期合并 Word）。"""

from __future__ import annotations

import json
import shutil
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .database import Database
from .path_utils import (
    build_time_subdirs,
    ensure_dir,
    get_iso_week_range,
    get_time_labels,
    sanitize_filename,
)
from .word_service import (
    WordFileLockedError,
    WordFileWriteError,
    assert_word_writable,
    create_period_word_document,
    html_to_plain_text,
)

# ---------- 路径与配置 ----------

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT_DIR / "config.json"
FRONTEND_DIR = ROOT_DIR / "frontend"
# Vue 构建产物优先；兼容旧原生静态前端
FRONTEND_DIST_DIR = FRONTEND_DIR / "dist"
STATIC_DIR = FRONTEND_DIST_DIR if FRONTEND_DIST_DIR.exists() else FRONTEND_DIR


def load_config() -> dict:
    defaults = {
        "host": "127.0.0.1",
        "port": 8765,
        "data_dir": "data",
        "default_docs_root": "data/documents",
        "auto_open_browser": True,
        "autosave_seconds": 30,
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

app = FastAPI(title="本地文档管理系统", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


def rebuild_period_word(
    category_id: int,
    period_type: str,
    period_label: str,
) -> Optional[dict]:
    """重建某个叶子分类 + 时间周期的合并 Word。"""
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
    try:
        create_period_word_document(
            output_path=output,
            category_path_names=path_names,
            period_type=period_type,
            period_label=period_label,
            projects=projects,
        )
    except (WordFileLockedError, WordFileWriteError):
        raise
    rel = str(Path(folder) / label / filename).replace("\\", "/")
    return db.upsert_period_file(
        category_id=category_id,
        period_type=period_type,
        period_label=period_label,
        relative_path=rel,
        word_filename=filename,
        project_count=len(projects),
    )


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


seed_default_categories()


# ---------- API：系统 ----------


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "app": "本地文档管理系统",
        "version": "2.0.0",
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


@app.post("/api/browse-folder")
def browse_folder(initial_path: Optional[str] = None):
    import subprocess
    import sys

    start_dir = str(DEFAULT_DOCS_ROOT)
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
                "$f.Description = '请选择分类对应的本地目录'; "
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
            title="请选择分类对应的本地目录",
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
            pf = rebuild_period_word(cid, ptype, lab)
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
        pf = rebuild_period_word(cid, ptype, lab)
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
        pf = rebuild_period_word(category_id, period_type, period_label)
    if not pf:
        raise HTTPException(404, "周期文件不存在")
    cat = db.get_category(category_id)
    if not cat:
        raise HTTPException(404, "分类不存在")
    fp = resolve_category_path(cat.get("path") or "") / pf["relative_path"]
    if not fp.exists():
        rebuild_period_word(category_id, period_type, period_label)
        fp = resolve_category_path(cat.get("path") or "") / pf["relative_path"]
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
        pf = rebuild_period_word(category_id, period_type, period_label)
    if not pf:
        raise HTTPException(404, "周期文件不存在")
    cat = db.get_category(category_id)
    if not cat:
        raise HTTPException(404, "分类不存在")
    fp = resolve_category_path(cat.get("path") or "") / pf["relative_path"]
    if not fp.exists():
        rebuild_period_word(category_id, period_type, period_label)
        fp = resolve_category_path(cat.get("path") or "") / pf["relative_path"]
    if not fp.exists():
        raise HTTPException(404, f"文件不存在：{fp}")
    filename = quote(fp.name)
    return FileResponse(
        path=str(fp),
        filename=fp.name,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


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
