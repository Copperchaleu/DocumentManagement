# 项目记忆

## 本地文档管理系统
- 本地办公网站 v2：多级分类 + 项目归档 + 周期合并 Word
- 一键启动：`start.bat` / `run.bat` / `start.ps1`（前台黑窗，关闭窗口即停服务）
- 默认端口 8765；bat 必须纯 ASCII + CRLF（中文 CMD 不能依赖 UTF-8 中文脚本）
- 曾尝试静默启动（pythonw/detached）不稳定，已回退为前台方式
- 后端：`backend/`（FastAPI）；前端源码 `web/`（Vue3+ElementPlus）；产物 `frontend/dist`
- 日常只 start；改前端才 `build-frontend.bat` / `npm run build`
- 分类树 parent_id；项目只属叶子分类；叶子目录可 browse-folder 选择
- 同一叶子分类 + 周/月/季 → 一个 Word；定时草稿 autosave_seconds=30
- 按周=ISO 周（周一~周日）
- UI 主题：靛蓝主色 `#4f46e5`，全局设计令牌在 `web/src/styles/app.css`

## 工作面板 /workbench（v2 单页三栏并排，非选项卡）
- `WorkbenchView.vue` = 全局 hero + `.workbench-columns` 三栏网格（待办/看板/随心记 同屏并排，非 tab）；待办整块抽到 `web/src/components/TaskBoard.vue`
- 区域二·数据看板：`DashboardPanel.vue` + `TrendChart.vue`（自绘 SVG，零新依赖）
- 区域三·随心记：`NotesPanel.vue`，localStorage key `document-management-workbench-notes-v1` `{id,content,createdAt,updatedAt}`
- 后端统计：`GET /api/stats/projects-summary`、`GET /api/stats/projects-trend?range=day|month|quarter`；仅统计 `status='saved'`，按 `created_at` 本地日期归窗；窗口 14天/6月/8季
- 待办 localStorage key 仍为 `document-management-workbench-tasks-v1`（抽取未改 key，零回归）

## 分类管理页拖拽排序（el-tree + reorder 端点）
- 分类管理页 `web/src/views/CategoriesView.vue` 由 el-table 重写为 **el-tree**（绑定 `appState.categoryTree`，`node-key=id`），支持拖拽排序。
- 约束：仅同级（同 parent_id）重排；跨父级/跨层级（type==='inner'）在 `allowDrop` 拦截并节流 `ElMessage.warning`；子树整体随节点移动天然成立。
- 更新策略：乐观更新——el-tree 就地移动 → 调 reorder；失败 `refreshCategories()` 回滚 + `toastError`（来自 `web/src/api/http.js`）。`saving` 期间 `:draggable=false` 防重入。
- 后端：`POST /api/categories/reorder`，body `{parent_id:int|null, ordered_ids:[int]}`（须覆盖该父级全部兄弟）；`database.reorder_siblings` 单事务 + 4 项校验（空/重复/同父/全覆盖），非法抛 ValueError→400 且事务回滚不改 sort_order。`categories.sort_order` 列现被正式写入启用。
- `CategoryUpdate`/`CategoryCreate` 已增 `sort_order` 可选字段；`PUT /api/categories/{id}` 透传。
- 设计文档：`docs/design_category_reorder.md`；测试：`qa/backend_reorder_test.py`、`qa/frontend_reorder_test.mjs`（31/31 PASS）。
