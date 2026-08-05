# 生产上线手册 · Word→Markdown 全链路迁移

> 范围变更（2026-08-05）：彻底移除 Word(.docx) 生成，历史 docx 一并迁为 Markdown；
> 存储、读取、编辑全链路统一为 Markdown。本文档为**受控上线步骤**，由运维在维护窗口执行。
> 自动化（代码+测试）已完成并验证，但**生产库的真实迁移与本地 .docx 归档尚未执行**（安全红线：不在对话内直接改生产数据）。

---

## 0. 最终 GO / NO-GO 判定

| 项目 | 结论 |
|------|------|
| 功能实现（T01–T09） | ✅ GO |
| 测试套件（`pytest tests/ -q`） | ✅ **21 passed, 1 skipped**，零收集错误 |
| 历史 docx→md 真实迁移（临时副本 POC） | ✅ 22/22 转换、22/22 写入、31 路径改写、0 损失 |
| `verify_no_docx.py` 代码层+数据层+文件系统层 | ✅ 通过（全链路无 .docx 残留） |
| 前端构建 | ✅ `web` 构建通过，md-editor-v3 已替换 wangEditor |
| 生产库真实迁移 / 本地归档 | ⏸ **待维护窗口执行（本手册第 3 节）** |

**结论：开发侧 GO；生产数据迁移按第 3 节在维护窗口受控执行。**

---

## 1. 已交付内容（变更清单速览）

**后端**
- `backend/markdown_utils.py`：`html_to_md`(markdownify/ATX)、`md_to_html`(mistune)、`docx_bytes_to_md`(mammoth)、纯文本往返比对工具。
- `backend/database.py`：`projects` 增 `content_format` + `content_html_backup`；`period_file_versions` 增 `md_content` + `file_format`（旧行标记 `file_format='docx'`）；`save/restore_period_file_version` 同步。
- `backend/word_service.py`：删除全部 python-docx 代码；新增 `build_period_markdown_document()` + `write_file_atomic()` + `rebuild_period_markdown`。
- `backend/main.py`：下载/恢复端点服务 `md_content`（`text/markdown`、`*.md`），保留 docx BLOB 作为回滚备份；本地同步优先用 `md_content`。

**前端**
- `web/src/views/ComposeView.vue`：md-editor-v3 替换 wangEditor，正文存 Markdown，30s 自动保存/字数/空校验。
- `web/src/utils/markdown.ts` + `web/src/components/MarkdownPreview.vue`：渲染/纯文本工具。
- `web/src/views/ProjectsView.vue` + `web/package.json`：依赖改为 `md-editor-v3` + `markdown-it`，移除 wangeditor。

**脚本 / 测试**
- `scripts/migrate_html_to_md.py`、`scripts/migrate_docx_versions_to_md.py`、`scripts/rollback_html_from_md.py`、`scripts/verify_no_docx.py`、`scripts/verify_word_versions.py`。
- `tests/test_markdown_migration.py`（16 passed + 1 skipped）、`tests/test_period_markdown_document.py`（5 passed，替代已删除的 `test_word_regen.py`）。
- 设计/PRD：`docs/prd_markdown_migration.md`、`docs/design_markdown_migration.md`、`docs/prd_markdown_migration_inc.md`、`docs/design_markdown_migration_inc.md` 及对应 mermaid。

**环境**
- `requirements.txt`：`markdownify==0.13.0`、`mistune==3.0.2`、`mammoth==1.8.0`；`python-docx` 已移除。
- 托管 venv：`/Users/graypaul/.workbuddy/binaries/python/envs/default/bin/python`（已装上述依赖）。

---

## 2. 前置检查（每次上线前必做）

```bash
cd /Users/graypaul/Projects/DocumentManagement

# 2.1 依赖就位
/Users/graypaul/.workbuddy/binaries/python/envs/default/bin/python -c \
  "import markdownify, mistune, mammoth; print('deps ok')"

# 2.2 回归测试绿灯
/Users/graypaul/.workbuddy/binaries/python/envs/default/bin/python -m pytest tests/ -q
# 期望：21 passed, 1 skipped

# 2.3 确认当前仍是 docx 旧态（应有 file_format='docx' 的历史版本与 wangEditor 正文）
/Users/graypaul/.workbuddy/binaries/python/envs/default/bin/python - <<'PY'
from backend.database import Database
db = Database("data/app.db")
with db.connect() as c:
    n = c.execute("SELECT COUNT(*) FROM period_file_versions WHERE file_format='docx'").fetchone()[0]
    print("历史 docx 版本数 =", n)
PY
```

---

## 3. 生产迁移演练（维护窗口执行）

> 顺序不可颠倒；每步先 `--dry-run` 看统计，确认无误后再 `--no-dry-run`。
> 所有命令默认指向 `data/app.db` 与 `data/documents`，可用 `--db` / `--documents-dir` 指向副本先演练。

### 3.0 备份（强制）
```bash
TS=$(date +%Y%m%d_%H%M%S)
cp data/app.db "data/app.db.bak_$TS"
cp -r data/documents "data/documents.bak_$TS"
echo "备份完成: app.db.bak_$TS, documents.bak_$TS"
```

### 3.1 停服（避免迁移期间写入竞争）
关闭前端/后端服务（如 `run.bat`/`start.ps1` 启动的进程），确认无活跃写入。

### 3.2 项目正文 HTML→Markdown（双写，可灰度）
```bash
PY=/Users/graypaul/.workbuddy/binaries/python/envs/default/bin/python

# 先看统计（默认 dry-run）
$PY scripts/migrate_html_to_md.py --dry-run --limit 50
# 灰度验证（先迁前 50 条）
$PY scripts/migrate_html_to_md.py --no-dry-run --limit 50
# 全量真实迁移
$PY scripts/migrate_html_to_md.py --no-dry-run
```
脚本对每条项目：`content_format` 置 `'md'`、`content` 写 Markdown、原 HTML 存入 `content_html_backup`（可回滚）。幂等：已迁移（`content_format='md'`）自动跳过。

### 3.3 历史周期版本 docx→Markdown（含本地 .docx 归档）
```bash
# 看统计
$PY scripts/migrate_docx_versions_to_md.py --dry-run
# 真实迁移 + 把现存本地 .docx 归档到 data/documents/_legacy_docx/
$PY scripts/migrate_docx_versions_to_md.py --no-dry-run --archive-legacy
```
脚本：对 `file_format='docx'` 的版本用 mammoth 转 md 写入 `md_content`、`file_format='md'`，原 docx BLOB 保留于 `file_content`（回滚用）；幂等。本地 `.docx` 迁后归档至 `_legacy_docx/`。

### 3.4 全链路无 .docx 校验（必须 exit 0）
```bash
$PY scripts/verify_no_docx.py
# 期望：[数据层] docx 真源=0 / [文件系统] 未归档 .docx 数=0 / 结果：通过
```

### 3.5 Markdown 版本语义校验
```bash
$PY scripts/verify_word_versions.py
# 期望：Markdown version verification OK
```

### 3.6 前端生产构建（若需）
```bash
cd web && npm install && npm run build && cd ..
```

### 3.7 冒烟测试（启服后）
1. 启动服务，登录。
2. 新建/编辑一个项目，确认编辑器为 Markdown、自动保存生效、正文入库为 md。
3. 进入周期文档页，点"重建周期文档"，确认生成 `.md` 并可下载 `.md`。
4. 下载/恢复一个历史周期版本，确认返回 Markdown 内容。
5. 检查 `data/documents/` 下新生成文件为 `.md`，无新增 `.docx`。

---

## 4. 回滚演练（出现严重问题时使用）

### 4.A 内容回滚（md→html，仅针对 projects.content）
```bash
PY=/Users/graypaul/.workbuddy/binaries/python/envs/default/bin/python
# 看统计
$PY scripts/rollback_html_from_md.py --dry-run
# 全量回滚（从 content_html_backup 还原，content_format 置 'html'）
$PY scripts/rollback_html_from_md.py --no-dry-run
# 或仅回滚指定项目
$PY scripts/rollback_html_from_md.py --no-dry-run --project-id <ID>
```
> 说明：`content_html_backup` 列保留原始 HTML，回滚不丢内容。周期版本回滚见 4.B。

### 4.B 整体回滚（库+数据目录，最快最稳）
```bash
# 停服后，用 3.0 的备份整体还原
TS=<对应备份时间戳>
cp "data/app.db.bak_$TS" data/app.db
rm -rf data/documents && cp -r "data/documents.bak_$TS" data/documents
```
> 周期版本 `file_format='docx'` 的 `file_content` BLOB 在迁移时**未被删除**，因此仅还原库即可恢复 docx 真源；`data/documents` 还原后本地亦回到 .docx 态。

### 4.C 回滚后校验
```bash
$PY -m pytest tests/ -q            # 仍应 21 passed, 1 skipped
$PY scripts/verify_word_versions.py
# 可选：确认历史 docx 版本数回到迁移前水平
```

---

## 5. 已知项与注意事项

- **范围变更影响项（已作废，不计入放行）**：原 P0-6（历史 Word BLOB）、P0-7（标题层级映射）、P0-11（md/html 路径 docx 一致）随 Word 移除作废；对应断言在 `test_markdown_migration.py` 中以 1 个 skip 保留标记。
- **影响报告往返差异（13/14 vs 14/14）**：旧影响报告脚本的纯文本归一口径与新管线略有出入，已被新 `_normalize_plain_text` 修复；属信息级已知项，不影响迁移保真（POC 22/22 零损失）。
- **mammoth 保真度**：本批历史 docx 为纯文本型，转换无损失；若后续出现含复杂表格/图片的 docx，需个案复核 `docx_bytes_to_md` 的 `loss_flags`。
- **python-docx 已彻底移除**：任何仍 `import docx` 的旧代码/测试都会失败——本仓库已无此类引用（`test_word_regen.py` 已删除并改写为 `test_period_markdown_document.py`）。
- **本地 .docx 归档路径**：`data/documents/_legacy_docx/`，保留期由运维按合规要求设定，非自动清理。

---

## 6. 验收口径（一句话）

开发侧：**21 passed, 1 skipped + 22/22 历史 docx 迁 md 零损失 + 全链路无 .docx 残留** → GO。
生产侧：按第 3 节在维护窗口执行并跑通 3.4–3.7，即视为上线完成。
