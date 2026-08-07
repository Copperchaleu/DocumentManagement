"""
项目编辑页 Tiptap 重构 —— QA 独立验证（功能闭环）

运行：
    /Users/graypaul/.workbuddy/binaries/python/envs/default/bin/python -m pytest qa/test_tiptap_editor.py -v

覆盖：
A. 静态/依赖：无 md-editor、有 @tiptap/*、关键产物组件完整
B. 后端工具：md_to_html / html_to_md / _project_body_to_markdown / get_plain_text / sniff
C. API：GET project content_for_editor 懒转不写库；autosave/save 显式 content_format=html
D. 前端源码契约：ComposeView / ProjectsView / TiptapEditor / HtmlPreview / html.ts
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_TMP_DIR = tempfile.mkdtemp(prefix="tiptap_qa_")
_TMP_DB = os.path.join(_TMP_DIR, "test_app.db")

import backend.database as _bd  # noqa: E402

_orig_db_init = _bd.Database.__init__


def _patched_db_init(self, db_path=None):
    _orig_db_init(self, Path(_TMP_DB))


_bd.Database.__init__ = _patched_db_init

import backend.main as main  # noqa: E402
from backend.markdown_utils import (  # noqa: E402
    get_plain_text,
    html_to_md,
    md_to_html,
    sniff_content_format,
)
from backend.word_service import _project_body_to_markdown, html_to_plain_text  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

WEB_SRC = ROOT / "web" / "src"
WEB_PKG = ROOT / "web" / "package.json"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def api():
    """隔离临时库的 TestClient；每个用例清空 projects / categories。"""
    with main.db.connect() as conn:
        # 按依赖顺序清理，避免外键约束失败
        for table in (
            "attachments",
            "period_file_versions",
            "period_files",
            "projects",
            "categories",
        ):
            try:
                conn.execute(f"DELETE FROM {table}")
            except Exception:
                pass
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def leaf_category(api):
    """创建带 path 的叶子分类，满足正式保存 require_leaf + 本地目录约束。"""
    cat_dir = Path(_TMP_DIR) / "cat_leaf"
    cat_dir.mkdir(parents=True, exist_ok=True)
    cat = main.db.create_category(
        name="QA叶子分类",
        path=str(cat_dir),
        description="tiptap qa",
        parent_id=None,
    )
    return cat


# ===========================================================================
# A. 静态 / 依赖 / 构建产物契约
# ===========================================================================


class TestStaticContracts:
    def test_web_src_has_no_md_editor_references(self):
        """web/src 内不得残留 md-editor / MdEditor 引用。"""
        offenders: list[str] = []
        for path in WEB_SRC.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in {".vue", ".ts", ".js", ".css", ".scss"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if re.search(r"md-editor|MdEditor", text):
                offenders.append(str(path.relative_to(ROOT)))
        assert not offenders, f"发现 md-editor 残留: {offenders}"

    def test_package_json_tiptap_no_md_editor(self):
        pkg = WEB_PKG.read_text(encoding="utf-8")
        assert "md-editor-v3" not in pkg
        for dep in (
            "@tiptap/vue-3",
            "@tiptap/starter-kit",
            "@tiptap/pm",
            "@tiptap/extension-underline",
            "@tiptap/extension-link",
            "@tiptap/extension-placeholder",
        ):
            assert dep in pkg, f"package.json 缺少 {dep}"

    def test_new_components_exist(self):
        assert (WEB_SRC / "components" / "TiptapEditor.vue").is_file()
        assert (WEB_SRC / "components" / "HtmlPreview.vue").is_file()
        assert (WEB_SRC / "utils" / "html.ts").is_file()

    def test_tiptap_editor_template_symbols_defined(self):
        """TiptapEditor 模板使用的关键符号在 script 中均有定义。"""
        text = (WEB_SRC / "components" / "TiptapEditor.vue").read_text(encoding="utf-8")
        # script / template 拆分
        script_m = re.search(r"<script[^>]*>(.*?)</script>", text, re.S)
        template_m = re.search(r"<template>(.*?)</template>", text, re.S)
        assert script_m and template_m
        script = script_m.group(1)
        template = template_m.group(1)

        # 从 template 提取 @click / :class 调用名
        used = set(re.findall(r"@click=\"([A-Za-z_]\w*)\"", template))
        used |= set(re.findall(r":class=\"\{[^}]*?\b([A-Za-z_]\w*)\(", template))
        used |= set(re.findall(r"v-show=\"!?(is[A-Za-z]+)\"", template))
        used |= set(re.findall(r":disabled=\"[^\"]*?\b(is[A-Za-z]+|can[A-Za-z]+)\b", template))
        used |= set(re.findall(r":editor=\"([A-Za-z_]\w*)\"", template))
        used |= set(re.findall(r"v-html=\"([A-Za-z_]\w*)\"", template))

        # 排除关键字与简单布尔字面
        skip = {"true", "false", "null", "undefined"}
        used = {u for u in used if u not in skip}

        defined: set[str] = set()
        defined |= set(re.findall(r"function\s+([A-Za-z_]\w*)\s*\(", script))
        defined |= set(re.findall(r"const\s+([A-Za-z_]\w*)\s*=", script))
        defined |= set(re.findall(r"let\s+([A-Za-z_]\w*)\s*=", script))
        # refs / computed / useEditor 结果
        for name in (
            "editor",
            "isPreview",
            "isFullscreen",
            "canUndo",
            "canRedo",
            "previewHtml",
            "rootRef",
            "isActive",
        ):
            if re.search(rf"\b{name}\b", script):
                defined.add(name)

        missing = sorted(u for u in used if u not in defined)
        assert not missing, f"TiptapEditor 模板引用未定义符号: {missing}"

    def test_html_preview_uses_sanitize(self):
        text = (WEB_SRC / "components" / "HtmlPreview.vue").read_text(encoding="utf-8")
        assert "sanitizeHtml" in text
        assert "v-html" in text

    def test_compose_view_frontend_contracts(self):
        text = (WEB_SRC / "views" / "ComposeView.vue").read_text(encoding="utf-8")
        assert "TiptapEditor" in text
        assert "htmlToPlainText" in text
        assert "content_format" in text
        assert "content_for_editor" in text
        assert "md-editor" not in text
        assert "MdEditor" not in text
        # 保存必须 append content_format=html
        assert re.search(r"append\(\s*['\"]content_format['\"]\s*,\s*['\"]html['\"]\s*\)", text)
        # loadEditPayload 消费 content_for_editor
        assert "content_for_editor" in text
        assert "function loadEditPayload" in text

    def test_projects_view_preview_branch(self):
        text = (WEB_SRC / "views" / "ProjectsView.vue").read_text(encoding="utf-8")
        assert "HtmlPreview" in text
        assert "MarkdownPreview" in text
        assert "content_format" in text
        # html → HtmlPreview，md → MarkdownPreview
        assert re.search(
            r"v-if=.*content_format.*=== ['\"]md['\"]",
            text,
        )
        assert "<HtmlPreview" in text


# ===========================================================================
# B. 后端转换 / 字数 / 周期正文
# ===========================================================================


class TestMarkdownHtmlUtils:
    def test_md_to_html_basic_semantics(self):
        md = "\n".join(
            [
                "# 标题一",
                "",
                "这是 **粗体** 与 [链接](https://example.com)。",
                "",
                "- 列表甲",
                "- 列表乙",
            ]
        )
        html = md_to_html(md)
        assert "<h1" in html.lower()
        assert "标题一" in html
        assert "<strong>" in html or "<b>" in html
        assert "粗体" in html
        assert "<a " in html and "https://example.com" in html
        assert "<ul" in html.lower() or "<li" in html.lower()
        assert "列表甲" in html

    def test_html_to_md_basic_semantics(self):
        html = (
            "<h2>章节</h2>"
            "<p>含 <strong>加粗</strong> 与 <a href=\"https://a.test\">点我</a>。</p>"
            "<ul><li>一项</li><li>二项</li></ul>"
        )
        md = html_to_md(html)
        assert re.search(r"^##\s*章节", md, re.M)
        assert "**加粗**" in md or "__加粗__" in md
        assert "https://a.test" in md
        assert "一项" in md and "二项" in md
        # 应是 MD，不再含主要标签
        assert "<h2" not in md

    def test_roundtrip_semantic_preserve(self):
        """md → html → md 后关键语义仍可识别（不要求逐字节恒等）。"""
        md = "# H1\n\n**bold** text\n\n1. one\n2. two\n\n[go](https://x.y)"
        html = md_to_html(md)
        back = html_to_md(html)
        plain_orig = get_plain_text(md, "md")
        plain_back = get_plain_text(back, "md")
        for token in ("H1", "bold", "one", "two", "go"):
            assert token in back or token in plain_back
            assert token in plain_orig
        assert "https://x.y" in back

    def test_project_body_to_markdown_html_branch(self):
        body = _project_body_to_markdown(
            {
                "content": "<h1>报题</h1><p><em>斜体</em></p>",
                "content_format": "html",
            }
        )
        assert body != "<h1>报题</h1><p><em>斜体</em></p>"
        assert "报题" in body
        assert re.search(r"^#\s*报题", body, re.M)
        assert "斜体" in body

    def test_project_body_to_markdown_md_passthrough(self):
        raw = "# 保持 Markdown\n\n- a\n- b"
        body = _project_body_to_markdown({"content": raw, "content_format": "md"})
        assert body == raw

    def test_sniff_vs_explicit_format_priority(self):
        """嗅探：有标签 → html；纯文本 → md。"""
        assert sniff_content_format("<p>x</p>") == "html"
        assert sniff_content_format("# heading only") == "md"
        assert sniff_content_format("") == "md"

    def test_get_plain_text_strips_html_tags(self):
        html = "<p>你好 <strong>世界</strong></p><ul><li>项A</li></ul>"
        plain = get_plain_text(html, "html")
        assert "<" not in plain
        assert "你好" in plain
        assert "世界" in plain
        assert "项A" in plain
        # 不应把标签算进字数噪声
        assert "strong" not in plain.lower()
        assert "ul" not in plain.lower()
        # 与 html_to_plain_text 一致
        assert plain == html_to_plain_text(html)

    def test_get_plain_text_md_branch(self):
        md = "# 题\n\n**粗**"
        plain = get_plain_text(md, "md")
        assert "题" in plain
        assert "粗" in plain
        assert "**" not in plain
        assert "#" not in plain or plain.count("#") == 0


# ===========================================================================
# C. API 集成：GET 懒转 / autosave / save content_format
# ===========================================================================


class TestProjectApiFormat:
    def test_get_project_md_lazy_convert_not_written(self, api, leaf_category):
        """content_format=md 的项目：GET 返回 content_for_editor 为 HTML，DB 仍为 md。"""
        md_content = "# 历史标题\n\n段落 **加粗** 内容\n\n- 点一"
        proj = main.db.create_project(
            title="历史MD项目",
            category_id=leaf_category["id"],
            content=md_content,
            content_preview="历史",
            time_modes=["month"],
            week_label=None,
            month_label=None,
            quarter_label=None,
            status="draft",
            content_format="md",
        )
        pid = proj["id"]

        resp = api.get(f"/api/projects/{pid}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["content_format"] == "md"
        assert data["content"] == md_content  # 真源未改
        editor_html = data.get("content_for_editor") or ""
        assert editor_html, "应返回 content_for_editor"
        assert "<" in editor_html  # 应为 HTML
        assert "历史标题" in editor_html
        assert "加粗" in editor_html
        # 二次确认库内仍为 md
        row = main.db.get_project(pid)
        assert row["content_format"] == "md"
        assert row["content"] == md_content

    def test_get_project_html_passthrough(self, api, leaf_category):
        html = "<h1>直开</h1><p>Tiptap HTML</p>"
        proj = main.db.create_project(
            title="HTML项目",
            category_id=leaf_category["id"],
            content=html,
            content_preview="直开",
            time_modes=["month"],
            week_label=None,
            month_label=None,
            quarter_label=None,
            status="draft",
            content_format="html",
        )
        resp = api.get(f"/api/projects/{proj['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["content_format"] == "html"
        assert data["content_for_editor"] == html
        assert data["content"] == html

    def test_autosave_explicit_html_format(self, api, leaf_category):
        html = "<p>自动保存 <strong>草稿</strong> 正文</p>"
        payload = {
            "title": "草稿标题",
            "category_id": leaf_category["id"],
            "content": html,
            "content_format": "html",
            "time_modes": ["week", "month"],
        }
        resp = api.post("/api/projects/autosave", json=payload)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body.get("ok") is True
        project = body["project"]
        assert project["content_format"] == "html"
        assert project["content"] == html
        assert project["status"] == "draft"
        # DB 二次确认
        row = main.db.get_project(project["id"])
        assert row["content_format"] == "html"
        assert "<strong>" in row["content"]

    def test_autosave_without_format_sniffs_html(self, api, leaf_category):
        """未显式 content_format 时，含标签内容 sniff 为 html。"""
        html = "<p>sniff 路径</p>"
        resp = api.post(
            "/api/projects/autosave",
            json={
                "title": "嗅探",
                "category_id": leaf_category["id"],
                "content": html,
                "time_modes": ["month"],
            },
        )
        assert resp.status_code == 200, resp.text
        project = resp.json()["project"]
        assert project["content_format"] == "html"

    def test_autosave_plain_md_without_format(self, api, leaf_category):
        """无标签纯文本 sniff 为 md（兜底路径）。"""
        md = "纯文本草稿无标签"
        resp = api.post(
            "/api/projects/autosave",
            json={
                "title": "纯MD草稿",
                "category_id": leaf_category["id"],
                "content": md,
                "time_modes": ["month"],
            },
        )
        assert resp.status_code == 200, resp.text
        project = resp.json()["project"]
        assert project["content_format"] == "md"

    def test_save_project_writes_html_format(self, api, leaf_category):
        """正式保存 Form 传 content_format=html → 库内 format=html。"""
        html = "<h2>正式保存</h2><p>内容 <em>斜体</em></p>"
        resp = api.post(
            "/api/projects",
            data={
                "content": html,
                "category_id": str(leaf_category["id"]),
                "title": "正式HTML项目",
                "time_modes": "month",
                "content_format": "html",
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["content_format"] == "html"
        assert data["content"] == html
        assert data["status"] == "saved"
        row = main.db.get_project(data["id"])
        assert row["content_format"] == "html"
        assert row["content"] == html

    def test_save_empty_html_rejected(self, api, leaf_category):
        """空正文（仅标签）正式保存应 400。"""
        resp = api.post(
            "/api/projects",
            data={
                "content": "<p></p><br/>",
                "category_id": str(leaf_category["id"]),
                "title": "空内容",
                "time_modes": "month",
                "content_format": "html",
            },
        )
        assert resp.status_code == 400
        assert "不能为空" in resp.text or "内容" in resp.text

    def test_md_open_then_save_promotes_to_html(self, api, leaf_category):
        """历史 md → GET 得 HTML → 保存 content_format=html 后真源升格。"""
        md_content = "# 旧稿\n\n遗留段落"
        proj = main.db.create_project(
            title="待升格",
            category_id=leaf_category["id"],
            content=md_content,
            content_preview="旧",
            time_modes=["month"],
            week_label=None,
            month_label=None,
            quarter_label=None,
            status="draft",
            content_format="md",
        )
        got = api.get(f"/api/projects/{proj['id']}").json()
        editor_html = got["content_for_editor"]
        assert "<" in editor_html

        # 用 Tiptap 产出的 HTML 正式保存
        new_html = "<h1>旧稿</h1><p>遗留段落（已编辑）</p>"
        resp = api.post(
            "/api/projects",
            data={
                "content": new_html,
                "category_id": str(leaf_category["id"]),
                "title": "待升格",
                "time_modes": "month",
                "project_id": str(proj["id"]),
                "content_format": "html",
            },
        )
        assert resp.status_code == 200, resp.text
        saved = resp.json()
        assert saved["id"] == proj["id"]
        assert saved["content_format"] == "html"
        assert saved["content"] == new_html
        row = main.db.get_project(proj["id"])
        assert row["content_format"] == "html"
        assert row["content"] == new_html


# ===========================================================================
# D. 写路径 resolve content_format 单元（与 main 逻辑对齐）
# ===========================================================================


def _resolve_content_format(content: str, content_format: str | None) -> str:
    """镜像 main.save_project / autosave 的 resolve 规则，便于纯单元断言。"""
    fmt_in = (content_format or "").strip().lower()
    if fmt_in in ("html", "md"):
        return fmt_in
    return sniff_content_format(content)


class TestResolveContentFormat:
    def test_explicit_html_wins_over_sniff_md_like(self):
        # 极边：看起来像 md 但显式声明 html
        assert _resolve_content_format("# not really md", "html") == "html"

    def test_explicit_md_wins_over_html_tags(self):
        assert _resolve_content_format("<p>x</p>", "md") == "md"

    def test_empty_falls_back_to_sniff(self):
        assert _resolve_content_format("<div>a</div>", None) == "html"
        assert _resolve_content_format("<div>a</div>", "") == "html"
        assert _resolve_content_format("plain", None) == "md"
        assert _resolve_content_format("plain", "bogus") == "md"
