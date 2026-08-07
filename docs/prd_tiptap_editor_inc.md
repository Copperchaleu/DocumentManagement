# 简单增量 PRD：项目编辑页编辑器重构为 Tiptap

> 文档角色：简单增量 PRD（产品需求层，不做架构/代码设计）  
> 文档负责人：产品经理 许清楚（Xu）  
> 关联现状：`web/src/views/ComposeView.vue`（md-editor-v3）+ `backend/markdown_utils.py` + 周期汇总 Markdown 落盘  
> 文档参考：https://tiptap.dev/  
> 技术栈（既定）：前端 Vue3 + Element Plus（`web/`），后端 FastAPI + SQLite（`backend/`）

---

## 0. 项目信息

| 项 | 内容 |
|---|---|
| Language | 简体中文 |
| Programming Language | Vue3 + Element Plus（前端）/ FastAPI + SQLite（后端）；不切换默认脚手架 |
| Project Name | `tiptap_editor_refactor` |
| 原始需求复述 | 将项目编辑页（Compose）的编辑器从 **md-editor-v3** 重构为 **Tiptap**；库内正文以 **JSON 或 HTML** 存储并与 Tiptap 配合；**周期汇总磁盘文件暂时继续保持 Markdown**，因此必须具备 HTML→Markdown（或 JSON→Markdown）转换能力；保留现有自动保存、字数统计、空内容校验、附件上传等能力；工具栏覆盖现有语义能力（不含纯展示样式）。 |

---

## 1. 产品目标（Product Goals）

1. **编辑体验切换**：项目编辑页提供稳定的 Tiptap 所见即所得富文本编辑，工具栏能力对齐现有语义范围，纯展示样式（字体/字号/颜色/对齐）不恢复。  
2. **存储与链路兼容**：以库内真源（HTML）驱动保存/自动保存/预览/字数/空校验；周期汇总落盘仍为 Markdown，且复用既有 `html_to_md` 管线，不推翻周期文件形态。  
3. **历史数据可编辑可演进**：既有 `content_format='md'` 与 `content_format='html'` 项目均可在 Tiptap 中打开编辑；用户再次保存后统一为 HTML 真源，过程可预期、可验收。

---

## 2. 用户故事（User Stories）

1. As a 项目撰写人, I want 在项目编辑页使用 Tiptap 所见即所得编辑正文 so that 我能直观设置标题、粗体、列表等，而不再依赖 Markdown 源码编辑。  
2. As a 项目撰写人, I want 自动保存、字数统计、空内容校验与附件上传继续可用 so that 重构编辑器不会打断既有写作与保存习惯。  
3. As a 文档管理员, I want 打开历史 Markdown 或历史 HTML 项目时内容正确显示在编辑器中 so that 历史数据不丢失且可继续维护。  
4. As a 汇报使用人, I want 保存项目后生成的周期汇总文件仍是 Markdown so that 现有周期文档阅读/下载/备份流程不变。  
5. As a 项目查看人, I want 项目详情页能正确预览重构后的 HTML 正文 so that 详情可读性不低于当前 Markdown 预览体验。

---

## 3. 需求池（Requirements Pool）

### P0（Must have）

| ID | 需求 | 验收要点 |
|---|---|---|
| **P0-1** | **Compose 页替换编辑器**：`ComposeView.vue` 移除 `md-editor-v3` 编辑入口，改用 **Tiptap** 作为唯一正文编辑器。 | 页面可打开、可输入、可保存；不再加载 MdEditor 作为主编辑器。 |
| **P0-2** | **DB 真源：HTML**：`projects.content` 存储 Tiptap 产出的 **HTML**；`content_format` 固定写为 **`html`**（保存/自动保存均一致）。 | 新建/编辑后库内为 HTML 标签结构；`content_format='html'`。 |
| **P0-3** | **Tiptap 能力覆盖现有工具栏语义**：标题、粗体、下划线、斜体、删除线、有序/无序列表、引用、链接、行内代码、代码块、撤销/重做；安装并启用对应官方/推荐扩展。 | 工具栏每项可点、文档结构变化符合预期；不含字体/字号/颜色/对齐。 |
| **P0-4** | **保存 / 自动保存保持**：手动保存与 **30s** 自动保存继续提交 `content`；空内容（纯文本为空）禁止正式保存；草稿自动保存规则与现逻辑一致（有标题或有正文才可草稿等）。 | 30s 草稿可回写；空正文正式保存被拦截并提示。 |
| **P0-5** | **字数统计口径**：按 HTML→纯文本（与后端 `get_plain_text`/`html_to_plain_text` 口径一致）统计，不计标签噪声。 | 字数与“可见文字”一致，不把标签算入字数。 |
| **P0-6** | **历史 `md` 项目可编辑**：打开 `content_format='md'` 时，将 Markdown **转换为 HTML** 后喂给 Tiptap；用户保存后真源变为 HTML，`content_format='html'`。 | 历史 MD 打开可见；保存后 format 与 content 均为 HTML。 |
| **P0-7** | **历史 `html` 项目直开**：`content_format='html'`（含早期 wangEditor 残留）直接 `setContent(html)`。 | 无二次破坏性转义；可继续编辑保存。 |
| **P0-8** | **周期汇总仍 Markdown**：保存触发的周期重建继续产出磁盘 **`.md`**；项目章节内容经 **`html_to_md`**（既有）再拼入 `build_period_markdown_document`。 | 保存后周期文件仍为 `.md`；HTML 结构语义（标题/列表/强调/链接/代码）可映射为 MD。 |
| **P0-9** | **详情预览适配 HTML**：`ProjectsView` 对 `content_format==='html'` 须以安全 HTML 渲染预览（不得继续 `pre` 原文甩标签）；`md` 路径可暂时保留 MarkdownPreview 直至无 MD 存量。 | HTML 项目详情可读，无原始标签堆叠；MD 存量仍可预览。 |
| **P0-10** | **依赖收敛**：引入 Tiptap 核心与所需扩展；**移除 md-editor-v3**（含样式与引用），避免双编辑器并存。 | `package.json` 无 `md-editor-v3`；构建/页面无其 CSS 残留为硬依赖。 |

### P1（Should have）

| ID | 需求 | 验收要点 |
|---|---|---|
| **P1-1** | 工具栏 / 编辑区视觉对齐靛蓝主题 `#4f46e5`（焦点环、主按钮激活态、链接色等）。 | 与现有工作台视觉一致，无明显违和。 |
| **P1-2** | 预览 / 全屏：保留“预览态”（只读渲染当前 HTML）与全屏编辑体验，交互可等价替代原 md-editor 的 preview/fullscreen。 | 预览只读正确；全屏可进可出。 |
| **P1-3** | 打开历史 MD 时转换位置明确落地（前端或后端二选一，见决议）；转换失败有可读错误提示且不静默丢内容。 | 异常路径可感知、可重试。 |
| **P1-4** | 链接编辑体验可用（插入/修改/取消链接），空 `href` 拦截。 | 链接可点击跳转（预览态）、可编辑。 |

### P2（Nice to have）

| ID | 需求 | 验收要点 |
|---|---|---|
| **P2-1** | 可选存 Tiptap JSON：新增 `content_json` 列双写，**本期不做**除非 HTML 往返出现不可接受结构损失。 | 默认不出工；若做需单独立项。 |
| **P2-2** | 批量脚本将存量 `content_format='md'` 一次性迁为 HTML（非打开时懒转换）。 | 可选运维脚本；非上线阻塞。 |
| **P2-3** | 表格/图片/提及等扩展能力。 | 明确 **Out of Scope**（本期不做）。 |

---

## 4. 关键决议（Decisions）

| # | 议题 | 决议 | 理由（基于工程现状，非臆造） |
|---|---|---|---|
| **D1** | DB 真源 HTML 还是 Tiptap JSON？ | **采用 HTML 作为 `projects.content` 真源 + `content_format='html'`**。JSON 仅作 P2 可选扩展（`content_json`），**本期不做**。 | ① 后端已有 `html_to_md`、`get_plain_text`、`sniff_content_format` 与 `content_format`/`content_html_backup` 迁移基建；② 周期汇总链路已按「项目内容 → MD → 拼装落盘」运转，HTML→MD 可直接复用；③ Tiptap `getHTML()` / `setContent(html)` 成熟稳定；④ 引入 JSON 真源需新增列、双写与全链路改造，性价比低。 |
| **D2** | 历史 `content_format='md'` 如何编辑？ | **打开时 MD→HTML**（懒转换），用户**保存后** `content` 写 HTML 且 `content_format='html'`。 | 避免强制全量迁移阻塞上线；与“编辑即演进”一致；后端已有 `md_to_html`（mistune）可供复用或前端等价转换。 |
| **D3** | 历史 `content_format='html'`？ | **直接喂给 Tiptap**，不做无谓的 HTML→MD→HTML 往返。 | 减少往返损失；兼容早期 wangEditor HTML 与新 Tiptap HTML 共存于同字段。 |
| **D4** | 周期汇总落盘格式？ | **继续 Markdown**；生成时对 HTML 真源走 **`html_to_md`** 再进入 `build_period_markdown_document` / `rebuild_period_markdown`。 | 用户明确要求；且现网周期文件与下载/版本体系已是 MD。 |
| **D5** | 是否移除 md-editor-v3？ | **是，本期移除**（依赖、组件引用、专用样式壳）。 | 单一编辑器降低维护与包体积；避免双格式编辑入口。 |
| **D6** | 纯展示样式？ | **不保留 / 不恢复**（字体族、字号、颜色、对齐）。 | 与历史 Markdown 迁移决议一致；工具栏不提供入口。 |
| **D7** | MD→HTML 转换执行侧（默认） | **优先后端转换**（打开项目接口或专用转换接口返回 HTML）；若实现成本更低，前端用可靠 MD 渲染库亦可，但**必须与后端纯文本/预览口径无显著偏差**。 | 后端已有 `md_to_html`；统一口径利于字数与导出一致。实现阶段二选一写死即可。 |
| **D8** | 后端保存契约 | 前端提交 HTML 字符串；后端继续可用 `sniff_content_format` 兜底，但**产品要求写路径应显式落 `html`**，避免把合法 HTML 误判的边界落到 `md`。 | 降低嗅探误判风险；与真源决议一致。 |

---

## 5. UI 设计要点（UI Design Draft）

### 5.1 布局

- 保持 Compose 页现有表单结构：标题、分类级联、时间周期、附件、保存区不变。  
- 正文区替换为「**Tiptap 工具栏 + 可编辑区域**」壳体，高度与原 `.md-editor-shell` 相当，占满主内容列。  
- 底部/侧旁保留：字数统计、自动保存状态文案、手动保存按钮。

### 5.2 工具栏按钮（P0 必现）

| 分组 | 按钮 |
|---|---|
| 行内样式 | 粗体、斜体、下划线、删除线、行内代码 |
| 块级结构 | 标题（H1–H3 足够；若实现成本低可到 H6）、引用、有序/无序列表、代码块 |
| 插入 | 链接 |
| 历史 | 撤销、重做 |
| 视图（P1） | 预览、全屏 |

**明确不出现**：字体族、字号、文字颜色、背景色、左右居中对齐、表格、图片（附件仍走既有上传区，不进编辑器内嵌图）。

### 5.3 样式主题

- 主色/激活态/焦点环对齐靛蓝 **`#4f46e5`**（与现网 Compose/工作台一致）。  
- 编辑区白底、清晰段落间距；代码块等宽字体、浅底区分。  
- 链接色可用主题靛色或可读的联动色，保证对比度。  
- 工具栏按钮选中态有明显高亮，避免“点了无反馈”。

### 5.4 交互

- 内容变更 → `dirty` → 触发自动保存计时逻辑（保持 30s）。  
- 正式保存：纯文本空 → 错误提示「请先粘贴或输入项目内容」。  
- 预览态只读，退出预览回到编辑。  
- 全屏时遮罩页面其余部分，Esc 或按钮退出。

---

## 6. 兼容与迁移策略

```
打开项目
  ├─ content_format == 'html'  → Tiptap.setContent(html)
  └─ content_format == 'md'    → MD→HTML → Tiptap.setContent(html)
保存 / 自动保存
  → content = Tiptap.getHTML()
  → content_format = 'html'
周期重建
  → 项目章节 = html_to_md(content)  （md 存量未改写前仍可走 get_plain_text/直出 MD 分支）
  → build_period_markdown_document → 磁盘 .md
详情预览
  ├─ format == 'md'   → MarkdownPreview（过渡）
  └─ format == 'html' → 安全 HTML 渲染
```

| 场景 | 策略 |
|---|---|
| 新项目 | 仅写 HTML 真源 |
| 编辑后的历史 MD | 懒转换，保存即升格为 HTML |
| 未再编辑的历史 MD | 允许存量保留 `md`，预览与周期链路继续兼容 |
| `content_html_backup` | 历史 MD 迁移遗留备份，**本期不强制清理**；不做二次回滚产品入口 |
| 全量 MD→HTML 脚本 | P2，非上线门槛 |
| 周期磁盘文件 | **暂不改为 HTML/JSON**，保持 Markdown |
| 附件 | 仍走现有 FormData 上传，与编辑器解耦 |

**风险与缓解（产品层）**

- MD↔HTML 往返可能损失边界格式 → 已决议不保留纯展示样式；接受标准语义级保真。  
- 详情页若仍对 HTML 使用 `<pre>` 会不可读 → **P0-9 强制改为 HTML 渲染**。  
- 双编辑器残留 → **P0-10 移除 md-editor-v3**。

---

## 7. 验收标准（Acceptance Criteria）

1. **编辑器**：Compose 页仅使用 Tiptap；工具栏 P0 能力逐项可用（标题/B/I/U/S/列表/引用/链接/行内代码/代码块/撤销重做）。  
2. **存储**：新建项目保存后 `projects.content` 为 HTML，`content_format='html'`。  
3. **历史 MD**：打开可见内容；保存后变为 HTML + `html`。  
4. **历史 HTML**：打开不乱码、可编辑、可保存。  
5. **自动保存**：30s 草稿逻辑仍有效；状态文案正常。  
6. **空校验 / 字数**：空正文不可正式保存；字数接近可见纯文本长度。  
7. **附件**：上传与随保存提交不受影响。  
8. **周期文件**：保存后相关周期文档仍为 Markdown；章节含对应语义内容（非空壳）。  
9. **详情预览**：HTML 项目可读渲染；MD 存量仍可预览。  
10. **依赖**：`md-editor-v3` 从工程依赖与引用中移除。  
11. **主题**：工具栏/焦点主色对齐 `#4f46e5`。  
12. **Out of Scope 未误做**：无字体颜色对齐、无编辑器内图片/表格（P2）、无周期改 HTML。

---

## 8. 待确认问题（Open Questions）

**无。**

（MD→HTML 执行侧前后端选择、Tiptap Vue 包装库具体包名等属实现细节，交架构/开发在详细设计中确定，不阻塞本 PRD。）

---

## 9. 范围边界（Scope）

| 在范围内 | 不在范围内 |
|---|---|
| Compose 编辑器 Tiptap 化 | 周期磁盘文件改为 HTML/JSON |
| HTML 真源与 format 写回 | 表格/图片/协同/评论等扩展 |
| 历史 MD/HTML 打开策略 | 恢复纯展示样式 |
| 周期 html_to_md 兼容 | 全量离线迁移脚本（P2） |
| 详情 HTML 预览 | 移动端专项编辑体验 |
| 移除 md-editor-v3 | 后端语言/框架更换 |

---

## 10. 参考与依据（事实来源）

- 编辑页：`web/src/views/ComposeView.vue`（`MdEditor`、`toolbars`、30s 自动保存、`mdToPlainText` 字数）  
- 详情：`web/src/views/ProjectsView.vue`（`content_format==='md'` → `MarkdownPreview`，否则 `pre`）  
- 工具：`backend/markdown_utils.py`（`html_to_md` / `md_to_html` / `sniff_content_format` / `get_plain_text`）  
- 周期：`backend/word_service.py` 的 `build_period_markdown_document`；`backend/main.py` 的 `rebuild_period_markdown`  
- 库表字段：`content_format`、`content_html_backup`（`backend/database.py`）  
- 依赖：`web/package.json` 当前含 `md-editor-v3`  
- 外部文档：https://tiptap.dev/

---

**文档结束。**
