"""Markdown 迁移工具集。

提供：
- ``sniff_content_format``：判断内容真源格式（'html' / 'md'）。
- ``html_to_md``：富文本 HTML → Markdown（迁移用，纯展示样式丢弃）。
- ``md_to_html``：Markdown → 标准 HTML（历史兼容，当前主链路不再使用）。
- ``md_to_plain_text`` / ``get_plain_text``：按格式取纯文本，供判空/字数/预览。
- ``docx_bytes_to_md``：历史 ``.docx`` BLOB → Markdown（mammoth→markdownify）+ 损失检测。

纯文本口径统一：``html_to_plain_text`` 由 ``word_service`` 提供（既有解析器），
``md_to_plain_text`` 先 mistune 渲染为 HTML 再走同一口径，保证往返校验公平。
"""

from __future__ import annotations

import re
from typing import Optional

from markdownify import markdownify as _markdownify_html

# 判定是否含 HTML 标签（与 word_service.html_to_plain_text 口径一致）。
_HTML_TAG_RE = re.compile(r"<\s*[a-zA-Z][^>]*>")


def sniff_content_format(content: str) -> str:
    """根据内容是否含 HTML 标签判断真源格式。

    含块级/内联 HTML 标签 → ``'html'``；否则 → ``'md'``。
    用于后端零契约变更地嗅探，前端仍只传 ``content`` 字符串。
    """
    raw = content or ""
    if _HTML_TAG_RE.search(raw):
        return "html"
    return "md"


def html_to_md(html: str) -> str:
    """将 wangEditor 等富文本 HTML 转为 Markdown。

    - ``heading_style="ATX"`` 确保 ``<h1>`` → ``#``，保留层级，与导出侧
      mistune 形成 ``#`` ↔ ``<h1>`` 闭环，保证标题映射一致（P0-7）。
    - 纯展示样式（font-family / font-size / color / text-align / ``<font>``）
      按已决议事项默认丢弃，不保留。
    - 后处理修复 markdownify 在「相邻内联样式边界」的保真缺陷：
      ``****`` 注入（D1）与 ``<br>`` 硬换行加倍（D2）。
    """
    raw = html or ""
    if not raw.strip():
        return ""
    # 已是纯文本或 Markdown（无 HTML 标签）则原样返回，避免二次转义。
    if not _HTML_TAG_RE.search(raw):
        return raw
    md = _markdownify_html(raw, heading_style="ATX")
    md = _normalize_emphasis_boundary(md)
    md = _normalize_line_breaks(md)
    return md.strip()


def _normalize_emphasis_boundary(md: str) -> str:
    """合并相邻粗体/斜体边界注入的字面定界符噪声（D1）。

    wangEditor 在「粗体跨 <span style> 边界」时会产出 ``**A****B**``，
    若直接渲染会在纯文本注入字面 ``****``（比丢失更糟）；粗体紧邻斜体边界
    会产出 ``**A***B*``。处理策略：
    - ``****`` → ``''``：相邻粗体定界符合并，A/B 成为同一连续粗体。
    - ``(?<=\\S)\\*\\*\\*(?=\\S)`` → ``*``：仅合并「夹在两个非空白字符之间」的
      ``***``（即定界符边界伪影），不影响合法的 ``***X***``（粗斜体，3 星定界器
      位于文本边缘，不会被此式匹配）。
    """
    md = md.replace("****", "")
    md = re.sub(r"(?<=\S)\*\*\*(?=\S)", "*", md)
    return md


def _normalize_line_breaks(md: str) -> str:
    """把 markdownify 的 ``<br>`` 硬换行（``"  \\n"``）压成单换行（D2）。

    markdownify 将 ``<br>`` 渲染为「两空格 + 换行」，mistune 再渲染会额外多一个
    换行，导致往返行数翻倍、与原文不一致。统一压成单换行，对齐 wangEditor
    ``<br>`` = 单换行的语义（同时保证 MD/HTML 两条 Word 路径行数一致）。
    """
    return re.sub(r" {2}\n", "\n", md)


def md_to_html(md: str) -> str:
    """将 Markdown 渲染为标准 HTML，供既有 ``_RichTextParser`` / ``_add_rich_content`` 复用。"""
    import mistune

    raw = md or ""
    if not raw.strip():
        return ""
    return mistune.html(raw)


def md_to_plain_text(md: str) -> str:
    """Markdown 取纯文本：先 mistune 渲染为 HTML，再走同一纯文本口径。

    与 ``html_to_plain_text`` 同构，保证往返校验公平（集合与顺序一致）。
    """
    from .word_service import html_to_plain_text

    html = md_to_html(md)
    return html_to_plain_text(html)


def get_plain_text(content: str, fmt: str) -> str:
    """按格式取纯文本。

    - ``fmt == 'md'``：走 ``md_to_plain_text``。
    - 其他（'html' 或未知）：走 ``html_to_plain_text``。
    """
    from .word_service import html_to_plain_text

    if fmt == "md":
        return md_to_plain_text(content)
    return html_to_plain_text(content)


def docx_bytes_to_md(docx_bytes: bytes) -> tuple[str, dict]:
    """历史 ``.docx`` BLOB → Markdown（mammoth→markdownify）+ 损失检测。

    复用与 ``projects.content`` 迁移同一条 HTML→MD 管线（markdownify），
    保证口径一致；docx 由自身 python-docx 生成、结构规整，mammoth 还原度高。

    返回 ``(md, loss_flags)``。``loss_flags`` 标注图片 / 表格 / 批注 /
    纯展示样式等标准 Markdown 无法等价表达、按已决议事项默认丢弃的构造，
    供《迁移影响报告》单列「历史 docx 损失」项。
    """
    import io

    import mammoth

    with io.BytesIO(docx_bytes) as buf:
        result = mammoth.convert_to_html(buf)
        html = result.value
        messages = result.messages
    md = _markdownify_html(html, heading_style="ATX")
    md = _normalize_emphasis_boundary(md)
    md = _normalize_line_breaks(md)
    md = md.strip()
    loss = _detect_docx_loss(html, messages)
    return md, loss


def _detect_docx_loss(html: str, messages: list) -> dict:
    """检测 docx→md 过程中默认丢弃/降级的构造，供《迁移影响报告》标注。"""
    loss = {
        "has_image": False,
        "has_table": False,
        "has_merged_cell": False,
        "has_comment": False,
        "style_loss": False,
    }
    if re.search(r"<\s*img\b", html, re.IGNORECASE):
        loss["has_image"] = True
    if re.search(r"<\s*table\b", html, re.IGNORECASE):
        loss["has_table"] = True
        if re.search(r"(colspan|rowspan)", html, re.IGNORECASE):
            loss["has_merged_cell"] = True
    msg_text = " ".join(str(m.get("message", "")) for m in (messages or []))
    if re.search(r"comment|批注|脚注|文本框|image|图片", msg_text, re.IGNORECASE):
        loss["has_comment"] = True
    if re.search(r"(font-|(text-align)|color\s*:|<font)", html, re.IGNORECASE):
        loss["style_loss"] = True
    return loss
