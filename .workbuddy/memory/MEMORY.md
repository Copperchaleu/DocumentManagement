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
