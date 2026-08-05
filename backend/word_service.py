"""周期文档以 Markdown 组装并落盘（彻底移除 Word/.docx）。

职责：
- ``build_period_markdown_document``：合并同周期项目的 Markdown 正文，
  输出一份完整的 Markdown 周期文档（标题 / 项目章节 / 元信息 / 分隔）。
- ``write_file_atomic``：原子写入任意字节（用于本地 ``.md`` 副本）。
- ``html_to_plain_text``：富文本/HTML 取纯文本（保留给 ``markdown_utils``
  的 ``md_to_plain_text`` 与往返校验复用，不依赖 python-docx）。

> 历史 ``period_file_versions`` 的 ``.docx`` BLOB 不再在此写出，已由
> ``scripts/migrate_docx_versions_to_md.py``（mammoth + markdownify）统一迁为
> Markdown 文本列 ``md_content``；``file_content`` BLOB 仅作回滚备份保留。
"""

from __future__ import annotations

import os
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable


class WordFileLockedError(Exception):
    """目标文件正在被其它程序占用（如被 Word/WPS/编辑器打开）导致无法写入。"""

    def __init__(self, path: Path | str, cause: Exception | None = None) -> None:
        self.path = Path(path)
        self.cause = cause
        super().__init__(str(self.path))


class WordFileWriteError(Exception):
    """文件写入失败（非占用类错误）。"""

    def __init__(self, path: Path | str, cause: Exception | None = None) -> None:
        self.path = Path(path)
        self.cause = cause
        super().__init__(str(self.path))


def write_file_atomic(content: bytes, output_path: Path) -> Path:
    """将任意字节先写临时文件再原子替换；占用/失败时给出明确异常。"""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_name(output_path.name + ".writing.tmp")
    try:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass
        tmp_path.write_bytes(content)
        try:
            os.replace(str(tmp_path), str(output_path))
        except PermissionError as e:
            raise WordFileLockedError(output_path, e) from e
        except OSError as e:
            if getattr(e, "winerror", None) == 32 or e.errno in (13, 11):
                raise WordFileLockedError(output_path, e) from e
            raise WordFileWriteError(output_path, e) from e
    except WordFileLockedError:
        raise
    except WordFileWriteError:
        raise
    except PermissionError as e:
        raise WordFileLockedError(output_path, e) from e
    except Exception as e:
        raise WordFileWriteError(output_path, e) from e
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass
    return output_path


# ---------------------------------------------------------------------------
# 富文本 → 纯文本（保留给 markdown_utils.md_to_plain_text / 往返校验复用）
# ---------------------------------------------------------------------------

class _RichTextParser(HTMLParser):
    """将受控 wangEditor HTML 解析为段落块和带格式的文字片段。"""

    BLOCK_TAGS = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "li", "pre"}
    INLINE_TAGS = {"strong", "b", "em", "i", "u", "s", "strike", "del", "a", "span", "font"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[dict[str, Any]] = []
        self._block: dict[str, Any] | None = None
        self._style_stack: list[dict[str, Any]] = [self._base_style()]
        self._inline_tags: list[str] = []
        self._list_stack: list[str] = []

    @staticmethod
    def _base_style() -> dict[str, Any]:
        return {
            "bold": False,
            "italic": False,
            "underline": False,
            "strike": False,
            "color": None,
            "href": None,
            "font_family": None,
            "font_size": None,
        }

    @staticmethod
    def _attrs(attrs) -> dict[str, str]:
        return {str(k).lower(): str(v or "") for k, v in attrs}

    @staticmethod
    def _css(style_text: str) -> dict[str, str]:
        result: dict[str, str] = {}
        for part in (style_text or "").split(";"):
            if ":" not in part:
                continue
            key, value = part.split(":", 1)
            result[key.strip().lower()] = value.strip()
        return result

    @staticmethod
    def _normalize_color(value: str | None) -> str | None:
        raw = (value or "").strip().lower()
        if re.fullmatch(r"#[0-9a-f]{6}", raw):
            return raw[1:].upper()
        if re.fullmatch(r"#[0-9a-f]{3}", raw):
            return "".join(ch * 2 for ch in raw[1:]).upper()
        match = re.fullmatch(r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", raw)
        if match:
            nums = [max(0, min(255, int(v))) for v in match.groups()]
            return "".join(f"{v:02X}" for v in nums)
        return None

    @staticmethod
    def _alignment(attrs: dict[str, str]) -> str:
        css = _RichTextParser._css(attrs.get("style", ""))
        align = (css.get("text-align") or attrs.get("align") or "left").lower()
        return align if align in {"left", "center", "right", "justify"} else "left"

    def _start_block(self, tag: str, attrs: dict[str, str]) -> None:
        self._flush_block()
        block_type = "list-item" if tag == "li" else tag
        self._block = {
            "type": block_type,
            "runs": [],
            "align": self._alignment(attrs),
            "list_type": self._list_stack[-1] if tag == "li" and self._list_stack else None,
            "list_depth": max(0, len(self._list_stack) - 1),
        }

    def _ensure_block(self) -> None:
        if self._block is None:
            self._start_block("p", {})

    def _flush_block(self) -> None:
        if self._block is None:
            return
        runs = self._block["runs"]
        while runs and not runs[-1]["text"]:
            runs.pop()
        if any(run["text"].strip() for run in runs):
            self.blocks.append(self._block)
        self._block = None

    def _append_text(self, text: str) -> None:
        clean = text.replace("\u00a0", " ")
        if not clean:
            return
        self._ensure_block()
        style = dict(self._style_stack[-1])
        runs = self._block["runs"]
        if runs and all(runs[-1].get(k) == style.get(k) for k in style):
            runs[-1]["text"] += clean
        else:
            runs.append({"text": clean, **style})

    def _push_inline_style(self, tag: str, attrs: dict[str, str]) -> None:
        style = dict(self._style_stack[-1])
        css = self._css(attrs.get("style", ""))
        if tag in {"strong", "b"} or css.get("font-weight", "").lower() in {"bold", "600", "700", "800", "900"}:
            style["bold"] = True
        if tag in {"em", "i"} or css.get("font-style", "").lower() == "italic":
            style["italic"] = True
        decoration = css.get("text-decoration", "").lower()
        if tag == "u" or "underline" in decoration:
            style["underline"] = True
        if tag in {"s", "strike", "del"} or "line-through" in decoration:
            style["strike"] = True
        color = self._normalize_color(css.get("color") or attrs.get("color"))
        if color:
            style["color"] = color
        font_family = css.get("font-family")
        if font_family:
            font_family = font_family.strip().strip('"').strip("'").strip()
            if "," in font_family:
                font_family = font_family.split(",", 1)[0].strip().strip('"').strip("'").strip()
            style["font_family"] = font_family
        font_size = css.get("font-size")
        if font_size:
            match = re.search(r"(\d+(?:\.\d+)?)\s*(px|pt|em|rem|%)?", font_size, re.IGNORECASE)
            if match:
                value = float(match.group(1))
                unit = (match.group(2) or "px").lower()
                if unit == "px":
                    style["font_size"] = round(value * 0.75, 2)
                elif unit == "pt":
                    style["font_size"] = value
        if tag == "a" and attrs.get("href"):
            style["href"] = attrs["href"].strip()
        self._style_stack.append(style)
        self._inline_tags.append(tag)

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        attr_map = self._attrs(attrs)
        if tag in {"ul", "ol"}:
            self._list_stack.append(tag)
        elif tag in self.BLOCK_TAGS:
            self._start_block(tag, attr_map)
        elif tag in self.INLINE_TAGS:
            self._push_inline_style(tag, attr_map)
        elif tag == "br":
            self._append_text("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.BLOCK_TAGS:
            self._flush_block()
        elif tag in {"ul", "ol"}:
            if self._list_stack:
                self._list_stack.pop()
        elif tag in self.INLINE_TAGS and len(self._style_stack) > 1:
            if self._inline_tags:
                self._inline_tags.pop()
            self._style_stack.pop()

    def handle_data(self, data: str) -> None:
        self._append_text(data)

    def close(self) -> None:
        super().close()
        self._flush_block()


def _parse_rich_text(content: str) -> list[dict[str, Any]]:
    parser = _RichTextParser()
    parser.feed(content or "")
    parser.close()
    return parser.blocks


def html_to_plain_text(content: str) -> str:
    """富文本转纯文本，兼容历史纯文本数据。"""
    raw = content or ""
    if not re.search(r"<\s*[a-zA-Z][^>]*>", raw):
        return raw
    blocks = _parse_rich_text(raw)
    return "\n".join("".join(run["text"] for run in block["runs"]).strip() for block in blocks)


# ---------------------------------------------------------------------------
# 周期文档 Markdown 组装
# ---------------------------------------------------------------------------

_PERIOD_CN = {"week": "周", "month": "月", "quarter": "季度"}


def _project_body_to_markdown(project: dict[str, Any]) -> str:
    """项目正文转 Markdown：``md`` 原样拼接；``html`` 经 markdownify 转换。

    与 ``projects.content`` 迁移共用同一 HTML→MD 管线（``markdown_utils.html_to_md``），
    保证单项目正文与全量迁移口径一致、保真。
    """
    from .markdown_utils import html_to_md

    content = project.get("content") or ""
    fmt = (project.get("content_format") or "html").lower()
    if fmt == "md":
        return content
    return html_to_md(content)


def build_period_markdown_document(
    category_path_names: Iterable[str],
    period_type: str,
    period_label: str,
    projects: list[dict[str, Any]],
) -> str:
    """把同一分类 + 同一时间周期的所有项目合并为一份 Markdown 周期文档。

    结构：文档 ``#`` 标题 → 元信息引用行 → 每个项目 ``## {序号}. {标题}``
    （含创建/更新/附件元信息）→ 项目正文（原样拼接或 HTML 转换）→ ``---`` 分隔。
    项目正文保真优先，默认不降级标题层级（与单项目内容往返一致）。
    """
    period_cn = _PERIOD_CN.get(period_type, period_type)
    cat_path = " / ".join([n for n in category_path_names if n]) or "未分类"

    lines: list[str] = []
    lines.append(f"# {cat_path} · {period_cn}报 {period_label}")
    lines.append("")
    lines.append(
        f"> 分类：{cat_path}  |  周期：{period_cn} {period_label}  |  项目数：{len(projects)}"
    )
    lines.append("")

    if not projects:
        lines.append("（本周期暂无项目）")
        lines.append("")
        return "\n".join(lines)

    for idx, project in enumerate(projects, start=1):
        lines.append(f"## {idx}. {project.get('title') or '未命名项目'}")
        lines.append("")

        bits = []
        if project.get("created_at"):
            bits.append(f"**创建**：{project['created_at']}")
        if project.get("updated_at"):
            bits.append(f"**更新**：{project['updated_at']}")
        atts = project.get("attachments") or []
        if atts:
            names = "、".join(
                a.get("original_name") or a.get("stored_name") or "" for a in atts
            )
            bits.append(f"**附件**：{names}")
        if bits:
            lines.append("  ".join(bits))
            lines.append("")

        body = _project_body_to_markdown(project)
        if body:
            lines.append(body)
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
