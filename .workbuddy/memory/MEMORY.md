# 项目记忆

## 本地文档管理系统
- 本地办公网站 v2：多级分类 + 项目归档 + 周期合并 Word
- 一键启动：`start.bat` / `run.bat` / `start.ps1`（前台黑窗，关闭窗口即停服务）
- 默认端口 8765；bat 必须纯 ASCII + CRLF（中文 CMD 不能依赖 UTF-8 中文脚本）
- 曾尝试静默启动（pythonw/detached）不稳定，已回退为前台方式
- 后端：`backend/`（FastAPI）；前端源码 `web/`（Vue3+ElementPlus）；产物 `frontend/dist`
- 日常只 start；改前端才 `build-frontend.bat` / `npm run build`
- ⚠️ **dist 干净重建**：`web/vite.config` 设 `emptyOutDir:false`（outDir 在 web 根外），`npm run build` 不清旧产物 → `frontend/dist` 会累积陈旧 chunk（曾堆到 14 个 CategoriesView + 48 个 index）。需彻底干净时先 `rm -rf frontend/dist` 再 `npm run build`（managed node 22.22.2）。懒加载视图 JS 与配套 CSS 哈希不同（如 `CategoriesView-BXY9Hl1l.js` + `BA-bnec9.css`），二者成对存在即正常，非断裂。
- 分类树 parent_id；项目只属叶子分类；叶子目录可 browse-folder 选择
- 同一叶子分类 + 周/月/季 → 一个 Word；定时草稿 autosave_seconds=30
- 按周=ISO 周（周一~周日）
- UI 主题：靛蓝主色 `#4f46e5`，全局设计令牌在 `web/src/styles/app.css`

## 工作面板 /workbench（v2 单页三栏并排，非选项卡）
- `WorkbenchView.vue` = 全局 hero + `.workbench-columns` 三栏网格（待办/看板/随心记 同屏并排，非 tab）
- 区域二·数据看板：`DashboardPanel.vue` + `TrendChart.vue`（自绘 SVG，零新依赖）；后端统计 `GET /api/stats/projects-summary`、`GET /api/stats/projects-trend?range=day|month|quarter`
- **数据已迁后端持久化（原 localStorage 方案已废弃）**：待办/随心记改存 SQLite 表 `workbench_tasks` / `workbench_notes`，经 `GET|POST|PUT|DELETE /api/workbench/{tasks,notes}` + `POST /api/workbench/migrate`（按 id 幂等）读写；以 `user_key` 隔离（缺省 `'default'`，前端 UUID 持久化于 localStorage `document-management-user-key`）。
- 前端：`TaskBoard.vue`/`NotesPanel.vue` 移除 localStorage 主存储，改调 `web/src/api/workbench.js`（`getUserKey` + CRUD + `migrateWorkbench`），乐观更新+失败回滚；首次空库且本地有旧数据自动迁移。
- 设计文档 `docs/workbench_persistence_design.md`；回归测试 `qa/test_workbench_persistence.py`（TestClient 真实 HTTP，10/10 PASS）。
- ⚠️ **Pydantic 边界约定**：工作面板模型字段名 snake_case + `alias` camelCase + `ConfigDict(populate_by_name=True)`；响应 `response_model_by_alias=True` 输出 camelCase，入参 `model_dump(by_alias=False)` 得 snake_case 落库。曾因漏加 alias 导致 dueTime/reminderAt 未落库——新增 camelCase 字段务必补 alias。
- ⚠️ 全局 `RequestValidationError → 400` 异常处理（main.py），使校验失败返回 400（契约要求）；此前默认 422，前端错误解析 status 无关故兼容。若需恢复 422，删 `_validation_exception_handler` 即可。
- ⚠️ **Vue SFC 前端验证约定**：`npm run build` 不校验模板里引用了未定义的变量/函数（编译期不报错），但运行时必崩（如 `computed is not defined`、删了函数模板仍在引用）。前端改动后 QA 必须 grep 模板残留的已删标识符 + 跑 build，不能仅以 build 通过判定可用。

## 分类管理页拖拽排序（el-tree + reorder 端点）
- 分类管理页 `web/src/views/CategoriesView.vue` 由 el-table 重写为 **el-tree**（绑定 `appState.categoryTree`，`node-key=id`），支持拖拽排序。
- 约束：仅同级（同 parent_id）重排；跨父级/跨层级（type==='inner'）在 `allowDrop` 拦截并节流 `ElMessage.warning`；子树整体随节点移动天然成立。
- 更新策略：乐观更新——el-tree 就地移动 → 调 reorder；失败 `refreshCategories()` 回滚 + `toastError`（来自 `web/src/api/http.js`）。`saving` 期间 `:draggable=false` 防重入。
- ⚠️ **`onNodeDrop` 必须 `await nextTick()` 后再读 `draggingNode.parent.childNodes` 组装 `ordered_ids`**：否则节点移动未完成就读到不全/错的兄弟顺序 → 后端全覆盖校验失败 400 → 前端 `catch` 回滚 → **排序永远落不了库**（典型「拖了没保存」根因）。组装用 `.map(n=>n.data?.id).filter(Boolean)`，`if(orderedIds.length<2) return`，成功后 `await refreshCategories()` 同步状态。
- 新建分类插最前：`database.create_category` 的 `sort_order is _UNSET` 分支 = 置 0 + 同级其余 `sort_order+1`（parent_id None 用 `WHERE parent_id IS NULL`）。已修「新建打乱顺序」。
- 后端：`POST /api/categories/reorder`，body `{parent_id:int|null, ordered_ids:[int]}`（须覆盖该父级全部兄弟）；`database.reorder_siblings` 单事务 + 4 项校验（空/重复/同父/全覆盖），非法抛 ValueError→400 且事务回滚不改 sort_order。`categories.sort_order` 列现被正式写入启用。
- `CategoryUpdate`/`CategoryCreate` 已增 `sort_order` 可选字段；`PUT /api/categories/{id}` 透传。
- 设计文档：`docs/design_category_reorder.md`；测试：`qa/backend_reorder_test.py`、`qa/frontend_reorder_test.mjs`（31/31 PASS）。
