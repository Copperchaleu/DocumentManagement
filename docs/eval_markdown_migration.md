# Word 富文本存储 → Markdown 迁移可行性评估

> 范围：本地文档管理系统 v2（FastAPI + Vue3/ElementPlus + python-docx）
> 目标：评估将「Word 文件存储方案」迁移为 Markdown，并把前端 wangEditor 富文本编辑器替换为 Markdown 编辑器的可行性、数据兼容方案与编辑器选型。
> 评估日期：2026-08-05

---

## 0. 结论摘要（TL;DR）

1. **可行性：高，且风险可控。**
   系统当前**真源并不是 Word，而是 `projects.content` 列里存储的 wangEditor HTML 富文本**；Word 只是「派生产物」（由同周期所有项目的 HTML 合并生成 `.docx` 字节，存进 `period_file_versions.file_content` BLOB 并同步到 `data/documents/*.docx`）。因此迁移的本质是「把 `content` 的语义从 HTML 改写为 Markdown」，Word 作为导出物可继续保留或重新生成，**不存在不可逆的文件格式绑定**。

2. **数据兼容：可做到「结构无损、样式可控丢弃」的无缝迁移。**
   - 标题 / 粗体 / 斜体 / 删除线 / 列表 / 引用 / 链接 —— 标准 Markdown 可 100% 承载，无损。
   - 字体族 / 字号 / 文字颜色 / 段落对齐 —— 标准 Markdown 无语义等价物，属**纯展示样式**。这是唯一的「内容损失」点，但对归档检索无价值（可在迁移时默认丢弃，或采用「Markdown + 内联 HTML」策略保留颜色，见 §3）。
   - 通过「全量备份 + 双写过渡 + 幂等迁移脚本 + 往返校验」四重保障，旧数据**不丢失、可回滚**。

3. **编辑器选型：推荐 `md-editor-v3`（首选），`Cherry Markdown`（备选/所见即所得）。**
   - 首选 **md-editor-v3**：Vue3 原生、集成成本最低、界面简洁、社区活跃、MIT 协议，最契合现有技术栈与「易用+简洁+稳定」要求。
   - 备选 **Cherry Markdown**（腾讯）：若最终用户（非技术）强烈需要「像 Word 一样直接看到排版」的所见即所得（WYSIWYG），Cherry 体验最佳且腾讯长期维护。
   - 不推荐 **TOAST UI Editor**（NHN 已进入维护模式，仓库已移交社区 fork，长期稳定性存疑）；**Vditor** 功能最全但明显过度、集成与定制成本高。

---

## 1. 现状剖析（基于代码实证）

### 1.1 存储模型（关键发现）

| 层 | 位置 | 内容 | 角色 |
|---|---|---|---|
| 真源 | `projects.content` (TEXT) | **wangEditor HTML 富文本** | 唯一数据真源 |
| 派生 | `period_file_versions.file_content` (BLOB) | 合并后的 `.docx` 字节 | 历史版本快照 |
| 派生 | `data/documents/<分类>/by_week|month|quarter/<周期>/*.docx` | 本地 Word 文件 | 人类可读归档/打开 |

- `backend/database.py` 的 `projects` 表：`content TEXT NOT NULL`、`content_preview TEXT`（纯文本预览）。
- `backend/word_service.py::build_period_word_document`：把同一「叶子分类 + 周期」下所有已保存项目的 `content` HTML，经 `_RichTextParser` 解析成块，再用 `python-docx` 写出 docx 字节。
- `backend/main.py::rebuild_period_word`：每次保存/删除项目都会重建对应周期的 Word，并把 docx 字节存入 `period_file_versions`，同时同步本地文件。

**结论**：Word 是「从 HTML 内容派生」的产物。只要 HTML（→Markdown）内容在，`rebuild_period_word` 就能随时重新生成 Word。迁移 Markdown 不会让已有 Word 失效——历史 docx 版本 BLOB 原样保留。

### 1.2 前端编辑器现状

`web/src/views/ComposeView.vue` 使用 `@wangeditor/editor-for-vue`（wangEditor v5）：
- `form.content` 绑定编辑器的 HTML 输出，原样 POST 给后端，存进 `projects.content`。
- 工具栏（`toolbarKeys`）：`headerSelect`、`fontFamily`、`fontSize`、`bold`、`italic`、`underline`、`through`、`color`、`bulletedList`、`numberedList`、`blockquote`、`justifyLeft/Center/Right/Justify`、`insertLink`、`undo`、`redo`。
- 图片/视频/表情已主动禁用（注释：「图片/视频/表情等无法导出 Word，已移除」）。
- 自动保存（30s 草稿）、字数统计、`htmlToPlainText` 判空均依赖 HTML。

### 1.3 导出管线要点

- `html_to_plain_text(content)`：判断有无 HTML 标签，无则原文，有则解析取纯文本。用于「判空 + 生成标题 + 生成 `content_preview`」。
- `_RichTextParser`：自研 HTML→段落块解析器，支持 h1–h6、列表（ol/ul，含嵌套深度）、引用、对齐、粗/斜/下划线/删除线、颜色、字体、字号、链接。
- 标题→Word 层级映射：`level = min(4, max(2, int(h)+1))`，即 h1→H2、h2→H3、h3+→H4（迁移时此映射约定需保持一致）。

---

## 2. 迁移可行性分析

### 2.1 为什么可行

1. **存储层零结构变动**：`content` 本就是 TEXT，只需改变其语义（HTML→MD）。过渡期可加 `content_format` 列（`'html'`/`'md'`）做分发，无需停机。
2. **Markdown 相对 HTML 的本质优势**：纯文本、体积小、可 diff/版本化、跨平台、长期可读、不被任何厂商绑定——正好契合「本地文档管理 + 归档」的诉求。
3. **Word 导出物可继续存在**：见 §1.1，Word 始终由内容重新生成，迁移不影响「还能导出/打开 Word」这一能力。
4. **编辑器输入仍是字符串**：Markdown 编辑器输出的也是字符串，`autosaveProject`/`saveProject` 的 `content` 字段契约不变，前端改动被限制在「编辑器组件」与「预览渲染」两处。

### 2.2 兼容性矩阵（最关键）

| 现有 HTML 元素 | 标准 Markdown 表达 | 迁移结果 |
|---|---|---|
| 标题 h1–h6 | `#` / `##` / … | ✅ 无损（保持现有 H2→H4 映射约定） |
| 粗体 / 斜体 / 删除线 | `**` / `*` / `~~` | ✅ 无损 |
| 有序 / 无序列表（含嵌套） | `1.` / `-` | ✅ 无损 |
| 引用 blockquote | `>` | ✅ 无损 |
| 链接 | `[text](url)` | ✅ 无损 |
| 段落对齐（左/中/右/两端） | 标准 MD 无原生对齐 | ⚠️ 丢失（可用内联 HTML `<div align>` 或扩展语法；或导出 Word 时统一左对齐） |
| 字体族（fontFamily） | 无等价 | ⚠️ 丢失（纯展示，归档无价值） |
| 字号（fontSize px/pt） | 无等价 | ⚠️ 丢失（纯展示） |
| 文字颜色（color） | 标准 GFM 无；可用内联 `<span style="color:">` | ⚠️ 默认丢失；如需保留用「MD + 内联 HTML」 |
| 组合样式（如红色加粗） | 加粗保留，红色丢失 | ⚠️ 部分丢失 |

**判定**：结构性内容（占归档价值 95%+）100% 无损；唯一的损失是字体/字号/颜色/对齐等**纯排版样式**，且这些在现有系统里本就只是「粘贴 Word 时带入的噪音」，对检索与归档意义有限。这是迁移的合理代价，而非「内容丢失」。

### 2.3 后端改造点

| 改造项 | 说明 |
|---|---|
| 新增 Markdown→docx 解析 | 用 `markdown-it` / `mistune` 解析 MD 为块，复用现有 `_add_rich_content` 写出逻辑（改入口，不动 python-docx 写出层） |
| 引入 Python Markdown 库 | `requirements.txt` 现仅有 fastapi/uvicorn/python-docx 等，需新增 `markdownify`（HTML→MD 迁移脚本用）与 `mistune`/`markdown`（MD→docx 导出用） |
| `html_to_plain_text` → `md_to_plain_text` | 判空、生成标题、生成 `content_preview` 改用 Markdown 纯文本提取 |
| `content_format` 分发 | 渲染/导出时按格式选择 HTML 解析器或 MD 解析器，支持双写过渡 |
| 历史 Word 版本 | 原样保留，`period_file_versions` BLOB 永不删除，可随时回看旧版式 |

### 2.4 前端改造点

- 用选定 Markdown 编辑器替换 `ComposeView.vue` 中的 wangEditor 组件，`form.content` 直接存 Markdown 文本。
- `autosave` / 草稿 / 字数统计 / 定时保存逻辑基本不变（编辑器提供 `onChange` 与内容字符串）。
- 项目详情/预览页引入 Markdown 渲染（md-editor-v3 自带预览；或 `markdown-it`）。

---

## 3. 数据兼容方案（无缝迁移，不丢内容）

### 3.1 总体策略：全量备份 + 双写过渡 + 幂等迁移 + 往返校验

**阶段 0 — 备份**
- 调用系统已有的 `Database.backup_to()` 做全量 SQLite 在线备份（`data/backups/app_*.db`）。

**阶段 1 — 双写过渡（零停机）**
- `projects` 表新增 `content_format` 列（默认 `'html'`）。
- 后端渲染/导出按 `content_format` 分发：新内容写 `'md'`，旧内容仍按 `'html'` 解析渲染。
- 前端：新旧编辑器共存或先仅对新内容启用 Markdown 编辑器。用户无感。

**阶段 2 — 一次性迁移脚本 `scripts/migrate_html_to_md.py`**
- 遍历 `content_format='html'` 的项目，用 HTML→MD 转换器（推荐 `markdownify` 或复用自研 `_RichTextParser` 思路反向输出 MD）转换：
  - 结构 100% 保留；
  - 字体/字号/颜色/对齐：默认丢弃（保留纯文本），并输出《迁移影响报告》统计受影响条数；
  - **可选增强**：若业务要求保留颜色，采用「Markdown 正文 + 内联 HTML `<span style="color:">`」策略（GFM 允许原始 HTML），保证在支持 HTML 的预览/导出中仍能着色。
- 重写 `content` 为 MD、`content_format='md'`、`content_preview` 重算。
- **可选**：对受影响周期重新 `rebuild_period_word`，使 docx 与新 MD 一致；历史 docx 版本 BLOB 原样保留。

**阶段 3 — 校验**
- 对每条转换做往返检查：`md→纯文本` 与 `原 html→纯文本` 应当一致（文本集合相等、顺序一致）。差异为 0 才算通过。
- 统计「仅样式损失」条目（字体/字号/颜色/对齐），由业务侧确认可接受。

**阶段 4 — 清理（可选，稳定后）**
- 移除 HTML 解析分支与 `content_format` 旧值；保留迁移报告与备份以备审计。

### 3.2 「不丢内容」的硬保证

- 迁移前全量备份；迁移脚本**幂等**（重跑安全，按 `project_id` 定位）。
- 原 HTML 不立即删除：可保留为 `content_html_backup` 列或独立 `projects_html_backup` 表，必要时一键回滚。
- Word 历史版本 BLOB 永久保留，旧版式随时可下载/恢复（现有 `/api/period-file-versions/{id}/download` 与 `/restore` 不受影响）。

### 3.3 风险与缓解

| 风险 | 缓解 |
|---|---|
| 字体/字号/颜色/对齐丢失 | 业务确认属纯展示样式、可接受；必要时用内联 HTML 保留颜色 |
| 用户从 Word 粘贴带复杂样式 | 新编辑器禁用富样式粘贴；迁移脚本归一化历史 HTML |
| 超大字段/性能 | Markdown 体积通常小于 HTML，反而更优 |
| 迁移脚本出错污染数据 | 先备份、先小批量灰度、幂等、可回滚 |

---

## 4. 候选编辑器选型

### 4.1 四维对比

| 维度 | Vditor (b3log) | Cherry Markdown (腾讯) | md-editor-v3 (imzbf) | TOAST UI Editor (NHN) |
|---|---|---|---|---|
| 框架/语言 | 原生 JS（可包 Vue） | 纯 JS + Vue/React 封装 | **Vue3 原生**（jsx+ts） | 原生 + Vue 封装 |
| 编辑模式 | MD / WYSIWYG / 即时渲染（三模式） | **WYSIWYG + 分栏 + 预览** | 分栏编辑 + 实时预览 | MD / WYSIWYG |
| 界面简洁 | 中（功能多，偏重） | **简洁美观，内置主题** | **简洁，暗黑模式** | 简洁 |
| 维护状态 | 活跃 | **活跃（2026-08 仍有 release）** | **活跃，社区响应快** | ⚠️ 维护模式（停新特性，仓库已移交 fork） |
| 体积/成本 | 大，定制成本高 | 中 | **轻量，集成成本低** | 中 |
| 中文支持 | 好 | **一流** | **好（默认中文）** | 一般 |
| 高级能力 | 图/流程图/脑图/数学/图可视化（溢出） | 流程图/公式/主题 | Mermaid/KaTeX/可定制工具栏 | 图表/表格/滚动同步 |
| 协议 | MIT | MIT | MIT | MIT |

### 4.2 逐项结论

- **Vditor**：能力最全，但本项目只需「标题/粗体/列表/引用/链接」这类基础能力，Vditor 的脑图、图可视化等是过度设计；原生 JS 需额外封装进 Vue3，配置复杂。**不推荐**。
- **Cherry Markdown（腾讯）**：纯 JS 内核 + 官方 Vue 封装，WYSIWYG 体验最接近 Word，对**非技术用户最友好**；内置主题美观、流程图/公式齐备、中文一流、腾讯背书长期稳定。**若最终用户强烈需要所见即所得，这是最佳选择。**
- **md-editor-v3**：Vue3 原生、开箱即用、左右分栏 + 实时预览对从 Word 过渡的用户足够友好、暗黑模式、Mermaid/KaTeX、工具栏可定制、MIT、社区活跃、体积小。**最契合现有技术栈与「易用+简洁+稳定」三项要求，推荐为首选。**
- **TOAST UI Editor**：成熟稳定但 **NHN 已进入维护模式（仅修关键 bug，停新特性），仓库移交社区 fork**，长期演进与依赖安全存在不确定性。**不推荐用于新建集成。**

### 4.3 推荐

- **首选：`md-editor-v3`** —— 满足易用性（分栏实时预览）、界面简洁、稳定性（活跃维护、MIT）、且与 Vue3/ElementPlus 技术栈零摩擦。
- **备选：`Cherry Markdown`** —— 当且仅当最终用户（非技术）要求「像 Word 一样所见即所得」时选用，WYSIWYG 体验最佳。
- **不推荐**：`TOAST UI Editor`（维护模式）、`Vditor`（过度复杂）。

### 4.4 与现有交互的契合度

| 现有能力 | 在 Markdown 编辑器下 |
|---|---|
| 30s 自动保存草稿 | ✅ 编辑器提供内容变更事件，复用现有 `autosaveProject` |
| 字数统计 | ✅ 编辑器输出文本即可统计 |
| 标题/粗体/列表/引用/链接 | ✅ 工具栏均有对应 |
| 段落对齐 | ⚠️ Markdown 无原生对齐；建议「导出 Word 时默认左对齐」或采用 MD 扩展 |
| 字体/字号/颜色 | ⚠️ 标准 MD 不保留；与迁移策略一致，默认放弃或内联 HTML 保留颜色 |

---

## 5. 实施路线建议

1. **决策点（需你确认）**
   - 是否保留字体/字号/颜色？（建议：不保留，视为排版噪音）
   - 最终用户是否需要 Word 式所见即所得？（决定选 Cherry 还是 md-editor-v3）
2. **POC（1–2 天）**：引入 `md-editor-v3` + Python Markdown 库，打通「HTML→MD→docx」一轮端到端验证。
3. **双写过渡（2–3 天）**：加 `content_format` 列 + 后端分发 + 前端新编辑器（新旧共存）。
4. **迁移脚本 + 校验（2–3 天）**：`scripts/migrate_html_to_md.py` + 往返校验 + 《迁移影响报告》。
5. **灰度演练（1–2 天）**：先新内容走 MD，跑全量迁移，质检样式损失项。
6. **清理（可选）**：稳定后移除 HTML 分支。

**粗估工作量**：后端 ~5–8 人日，前端 ~3–5 人日，测试与迁移演练 ~3 人日，合计约 **1.5–2 周（单人）**。

---

## 6. 关键风险一览

- **唯一实质损失**：字体/字号/颜色/对齐等纯展示样式在标准 Markdown 中无等价；结构性内容零损失。
- **最大依赖风险**：引入 1–2 个 Python Markdown 库与 1 个前端编辑器依赖，需锁定版本并纳入 `requirements.txt` / `package.json`。
- **Word 兼容**：迁移后 Word 仍是派生导出物，新版式以 Markdown 真源为准；旧 Word 版本历史永久保留。

---

*附：本评估基于对 `backend/word_service.py`、`backend/database.py`、`backend/main.py`、`web/src/views/ComposeView.vue` 的源码实证，以及候选编辑器公开维护状态检索（截至 2026-08）。*
