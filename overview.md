# Tiptap 编辑器重构交付总览

## 做了什么

将项目编辑页（Compose）从 **md-editor-v3（Markdown）** 重构为 **Tiptap（所见即所得）**。

| 层级 | 变更 |
|---|---|
| 编辑器 | `TiptapEditor.vue`：标题/B/I/U/S/列表/引用/链接/代码/撤销重做/预览/全屏 |
| DB 真源 | `projects.content` = **HTML**，`content_format='html'` |
| 周期磁盘 | **仍为 Markdown**（`html_to_md` → `build_period_markdown_document`） |
| 历史兼容 | `md` 打开时后端懒转 `content_for_editor`（不写库），保存后升格 html |
| 详情预览 | `html` → `HtmlPreview`；存量 `md` → `MarkdownPreview` |

## 关键文档

- `docs/prd_tiptap_editor_inc.md`
- `docs/design_tiptap_editor_inc.md`

## 验证结果

- 前端 `npm run build`：✅ 成功
- `qa/test_tiptap_editor.py`：**26/26 PASS**
- `web/src` 无 md-editor 残留
- routing：**NoOne**（无阻断缺陷）

## 用户下一步

1. 重启服务：`start.bat` / `start.ps1` / `run.bat`（或等价启动脚本）
2. 打开「新建/编辑项目」，确认 Tiptap 工具栏可用
3. 编辑历史 Markdown 项目并保存 → 应升格为 HTML 真源
4. 检查对应周期汇总 `.md` 仍生成且含语义内容
5. 若前端未更新，干净重建：`rm -rf frontend/dist && cd web && npm run build`
