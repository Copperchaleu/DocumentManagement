"""T05 后端验证：周期 Markdown 文档组装（替换废弃的 docx 重生成测试）。

范围变更（2026-08-05）：Word(.docx) 已彻底移除，历史 docx 一并迁为 Markdown。
原 `tests/test_word_regen.py` 依赖已删除的 `backend.word_service.build_period_word_document`
与 `python-docx`，在 pytest 收集阶段即 `ImportError`，拖垮整个测试套件。

本模块改为覆盖新函数 `build_period_markdown_document(category_path_names,
period_type, period_label, projects) -> str`（返回 Markdown 文本，非 bytes），
验证：文档 H1 标题 + 元信息行、md 原样保留、html 经 `html_to_md` 转换、
多项目以 `## {序号}. 标题` 排序并 `---\u200b` 分隔、空项目列表不抛异常。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from backend.markdown_utils import html_to_md  # noqa: E402
from backend.word_service import build_period_markdown_document  # noqa: E402

# 与迁移测试一致的结构化样本（覆盖标题/粗体/斜体/删除线/有序无序/嵌套/引用/链接/样式）。
SAMPLE_HTML: list[str] = [
    "<h1>一季度经营总结</h1>",
    "<p>这是<strong>重点内容</strong>与<em>强调说明</em>。</p>",
    "<p>原计划<s>已取消</s>的项目安排。</p>",
    "<ol><li>第一步准备材料</li><li>第二步提交审批</li><li>第三步归档留存</li></ol>",
    "<ul><li>苹果</li><li>香蕉</li><li>橙子</li></ul>",
    (
        "<ul><li>水果"
        "<ul><li>苹果</li><li>香蕉</li></ul>"
        "</li><li>蔬菜</li></ul>"
    ),
    "<blockquote>客户要求本周内交付初稿，逾期将影响验收。</blockquote>",
    '<p>详见规范文档<a href="https://example.com/spec">点击查看</a>。</p>',
    (
        '<p style="text-align: center;">'
        '<span style="color: rgb(255, 0, 0); font-size: 20px; '
        'font-family: 微软雅黑;">红色标题文字</span></p>'
    ),
    (
        "<h2>章节二</h2>"
        "<p>正文段落，含<strong>粗体</strong>与<em>斜体</em>。</p>"
        "<blockquote>重要提示</blockquote>"
        "<ul><li>要点一</li><li>要点二</li></ul>"
    ),
]


def _make_project(html: str, fmt: str) -> dict:
    content = html if fmt == "md" else html_to_md(html)
    return {
        "title": "项目P",
        "content": content,
        "content_format": fmt,
        "attachments": [],
        "created_at": "2026-08-01 00:00:00",
        "updated_at": "2026-08-01 00:00:00",
    }


def _build_md(projects: list[dict]) -> str:
    return build_period_markdown_document(
        category_path_names=["测试分类"],
        period_type="month",
        period_label="2026-08",
        projects=projects,
    )


def test_document_has_h1_title_and_meta_line():
    """文档首行 H1 标题、含元信息引用行（> 分类：...）。"""
    out = _build_md([_make_project(SAMPLE_HTML[0], "md")])
    lines = out.splitlines()
    assert lines[0].startswith("# 测试分类 · 月报 2026-08"), (
        f"标题首行不符：{lines[0]!r}"
    )
    assert any(ln.startswith("> 分类：") for ln in lines), (
        f"缺少元信息引用行：\n{out}"
    )


def test_md_format_preserved_verbatim():
    """content_format='md' 的原文 Markdown 应逐字保留，不经转换。"""
    raw_md = "# 原始标题\n\n这是**粗体**内容。"
    project = {
        "title": "项目P",
        "content": raw_md,
        "content_format": "md",
        "attachments": [],
    }
    out = _build_md([project])
    assert raw_md in out, f"md 原样内容未逐字保留：\n{out}"


def test_html_format_converted_via_html_to_md():
    """content_format='html' 的 <h1> 应经 html_to_md 转为 Markdown 标题。"""
    html = "<h1>一季度经营总结</h1>"
    project = _make_project(html, "html")
    out = _build_md([project])
    assert "# 一季度经营总结" in out, f"html 未转 md：\n{out}"


def test_multiple_projects_ordered_with_h2_and_separator():
    """多项目按 `## {序号}. 标题` 排序，且含 `---` 分隔。"""
    projects = [_make_project(h, "md") for h in SAMPLE_HTML[:3]]
    out = _build_md(projects)
    assert "## 1. 项目P" in out
    assert "## 2. 项目P" in out
    assert "## 3. 项目P" in out
    assert "---" in out


def test_empty_projects_does_not_raise():
    """空项目列表应返回「本周期暂无项目」且不抛异常。"""
    out = _build_md([])
    assert "本周期暂无项目" in out
