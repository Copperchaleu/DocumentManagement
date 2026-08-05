# 增量 PRD：移除 Word 全链路 + 历史 period_file_versions 统一迁为 Markdown

> 文档角色：增量 PRD（仅描述相对基础 PRD `prd_markdown_migration.md` 的**变更部分**）
> 基础文档：`docs/prd_markdown_migration.md`（产品目标、用户故事、UI 要点等未提及者维持不变）
> 文档负责人：产品经理 许清楚（Xu）

---

## 1. 变更摘要（Change Summary）

| 维度 | 基础 PRD | 本次变更 |
|---|---|---|
| 内容真源 | `projects.content` HTML → Markdown | 不变 |
| Word 角色 | Word 为派生产物，仍生成/存储 `.docx` | **彻底移除 Word**：全链路只存/服务 Markdown，不再生成或存储 `.docx` |
| 历史 `period_file_versions` | BLOB `.docx` 永久保留、不参与改写 | **一并迁移为 Markdown**，实现全量统一（有损需标注） |
| 周期文档落盘 | `data/documents/*.docx` | `data/documents/*.md` |
| 下载/恢复端点 | 服务 `.docx` | 改为服务 `.md` |
| `python-docx` | 依赖锁定保留（MD→docx 导出） | 降级为可选/可移除（不再需要 MD→docx） |
| 验收核心 | docx 内容与历史一致 | `.md` 内容正确、历史 docx→md 可执行且标注损失、下载得 `.md` |

---

## 2. 已决议事项（更新）

基础 PRD 的**决议 1（纯展示样式不保留）、决议 2（编辑器选 md-editor-v3，Cherry 仅备选不实施）维持不变**。新增决议：

- **决议 3（本次新增）：彻底移除 Word，全链路 Markdown 化。** 系统不再生成、存储或导出 `.docx`；周期文档以 Markdown 组装并落盘/入库；`period_file_versions` 自本变更起存储 Markdown 文本（不再存 docx BLOB）；历史既有 `.docx` BLOB 一并迁移为 Markdown，实现全量统一。

---

## 3. 范围边界（更新）

替换基础 PRD 第 8 节对应条目：

| 条目 | 新表述 |
|---|---|
| 原「Word 作为派生产物」相关 | **period 文档以 `.md` 落盘、`period_file_versions` 存储 Markdown 文本**，全链路不再出现 `.docx`。 |
| 原「不改动历史 Word 版本 BLOB 的存储与恢复机制」 | **历史 `period_file_versions` 中的 `.docx` BLOB 纳入迁移**，统一转为 Markdown（迁移有损需标注，见验收）。 |

其余 Out of Scope 条目（不做架构设计、不保留纯展示样式、不实施 Cherry）不变。

---

## 4. 需求池变更（Requirements Pool Δ）

### 4.1 修改的需求

**P0-6（重写）— 历史 docx 一并迁为 Markdown（全量统一）**
- 旧：历史 Word 版本 BLOB 永久保留，不参与改写。
- 新：将 `period_file_versions` 中既有 `.docx` BLOB 全部迁移为 Markdown 文本，实现与 `projects.content` 的**全量统一**；该迁移**有损**，须在《迁移影响报告》中单列「历史 docx 损失」项并标注（docx 特有构造如表格/图片/复杂排版在标准 Markdown 下无法等价表达）。

**P0-11（重写）— 周期文档以 Markdown 组装并落盘/入库**
- 旧：`rebuild_period_word` 改为读取 Markdown 真源重新生成 docx，复用现有写出逻辑。
- 新：周期文档生成逻辑改为**以 Markdown 组装**——合并同周期项目 Markdown 内容，落盘 `data/documents/<分类>/by_week|month|quarter/<周期>/*.md`，并将 Markdown 文本写入 `period_file_versions`（替代原 docx BLOB）。不再调用 `.docx` 写出。

### 4.2 新增的需求

**P0-13 — 下载/恢复端点改为服务 `.md`**
- `/api/period-file-versions/{id}/download` 与 `/restore` 由返回 `.docx` 改为返回对应 Markdown 文本（`.md`）；前端下载入口文案与图标由 Word 改为 Markdown。
- 验收：端点返回内容类型 `text/markdown`，文件后缀 `.md`，可正常打开/恢复。

**P0-14 — `period_file_versions` 结构适配**
- 该表存储形态由「docx BLOB」改为「Markdown 文本列」；需新增格式标识（如 `file_format='md'`）以支持迁移期双写过渡与回滚，并保障条目与历史版本一一对应。
- 验收：迁移前后 `period_file_versions` 条目数量一致（docx BLOB → md 文本一一对应），无遗漏版本。

### 4.3 受影响、需扩展的既有需求

- **P0-3（迁移脚本，扩展）**：`scripts/migrate_html_to_md.py` 除 `projects.content` 的 HTML→MD 外，**新增对 `period_file_versions` 既有 `.docx` BLOB 的 docx→MD 转换分支**；两部分均须幂等、`project_id`/版本定位可重跑。
- **P0-1（备份，维持）**：迁移前全量在线备份仍为前置（现需同时覆盖 `projects` 与 `period_file_versions` 的历史 docx）。
- **P0-5（原 HTML 可回滚，维持并扩展）**：除 `projects.content` 的 HTML 备份外，历史 docx BLOB 在迁移前亦应保留备份（独立备份表/列），支持一键回滚至 docx 真源。
- **P1-1（迁移影响报告，扩展）**：除「仅样式损失」外，**单列「历史 docx 损失」项**（表格/图片/复杂排版等 docx 特有构造的损失统计），供业务签字确认。
- **P1-2（受影响周期重建，重写）**：原「重新 `rebuild_period_word` 使 docx 与新 MD 一致」改为「重新以 Markdown 组装受影响的周期文档（`*.md` 落盘 + `period_file_versions` 写入），使周期文档与新真源一致」。

### 4.4 降级/移除的需求

- **P0-12（依赖，调整）**：见第 5 节依赖变更——`python-docx` 由必选降级为可选/可移除；`markdownify` 仍用于 HTML→MD 迁移。
- **P2 中「颜色保留用内联 HTML」等**维持；原涉及 docx 一致性的任何隐含假设作废。

### 4.5 依赖变更（原 P0-12）

| 依赖 | 变更 |
|---|---|
| `python-docx` | 由必选锁定 → **可选/可移除**。若保留，仅用于读取历史 `.docx` BLOB 以做 docx→MD 迁移；MD→docx 导出路径移除，不再需要其写出能力。 |
| `markdownify` | 维持，用于 `projects.content` 的 HTML→MD 迁移。 |
| docx→MD 转换能力 | 新增需求：历史 `.docx` BLOB 需转为 Markdown。方案二选一——(a) 保留 `python-docx` 仅读取文本再做 MD 归一化；(b) 引入 docx→md 专用库。具体选型由架构师评估（见 Open Questions）。 |
| `mistune`/`markdown`（原 MD→docx 导出用） | 原导出用途移除；若周期文档 Markdown 渲染仍需，可保留用于预览，非强制。 |

---

## 5. 验收标准变更（Acceptance Criteria Δ）

替换基础 PRD 7.1 中与 docx 相关的条目：

| 维度 | 新验收条件（替换原 docx 一致性条目） |
|---|---|
| **周期文档 `.md` 正确** | 重新以 Markdown 组装的周期文档落盘 `data/documents/*.md` 且写入 `period_file_versions`，内容由同周期项目 Markdown 正确合并、无截断。 |
| **历史 docx→md 可执行且标注损失** | `period_file_versions` 全部历史 `.docx` BLOB 已转为 Markdown；《迁移影响报告》单列「历史 docx 损失」项（表格/图片/复杂排版等），经业务签字确认。 |
| **下载得到 `.md`** | `/api/period-file-versions/{id}/download` 与 `/restore` 返回 `text/markdown` 的 `.md` 内容，可正常打开/恢复。 |
| **版本条目一致性** | 迁移前后 `period_file_versions` 条目数量一致（docx BLOB → md 文本一一对应），无版本丢失。 |
| **全链路无 `.docx`** | 系统内不再生成、存储或导出 `.docx`；`data/documents/` 下无新增 `.docx`，仅有 `.md`。 |

> 移除原「导出一致：基于 Markdown 重新生成的 docx 与迁移前 docx 文本内容一致」条目（Word 已不存在）。
> 其余验收条目（备份存在、往返校验 100%、结构无损、样式损失已确认、可回滚、编辑器替换生效、零停机）**维持不变**。

**上线放行门槛（更新）**：P0-1 ~ P0-14 全部完成；往返校验通过率 100%；《迁移影响报告》（含历史 docx 损失项）经业务确认；回滚演练成功；全链路无 `.docx` 残留。

---

## 6. Open Questions（需澄清/待架构师评估）

1. **历史 docx→MD 选型**：保留 `python-docx` 仅读取文本，还是引入 docx→md 专用库？影响损失程度与工作量（架构师定）。
2. **docx 特有构造处理**：表格、图片等在标准 Markdown 下无等价表达，历史迁移是否接受纯文本化丢失，或采用 GFM 扩展/内联 HTML 部分保留？（建议：与决议 1 一致，默认丢弃，标注即可。）
3. **`period_file_versions` 结构**：Markdown 文本列与格式标识的具体落地方式（列改造 vs 新表），由架构师在设计中定。

---

## 7. 不再适用的旧条目（作废清单）

- 基础 PRD P0-6「历史 Word 版本 BLOB 永久保留」→ 已被 P0-6（重写）取代。
- 基础 PRD P0-11「Word 重生成读 Markdown」→ 已被 P0-11（重写）取代。
- 基础 PRD 7.1「导出一致（docx 与迁移前一致）」→ 随 Word 移除作废。
- 基础 PRD 第 8 节「不改动历史 Word 版本 BLOB 的存储与恢复机制」→ 已被范围边界更新取代。
- 原「MD→docx 导出」相关依赖与逻辑假设 → 全部作废。
