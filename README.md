# 本地文档管理系统

完全本地运行的办公小站：粘贴项目信息 → 生成/合并 Word，并按**多级分类 + 周/月/季**归档到本机目录。

## 启动方式

- **Windows 日常使用**：双击 `start.bat`（或 `run.bat`）
- **macOS 日常使用**：双击 `start.command`
- **开发/改前端时**：才需要 `npm install` + `npm run build`  
- 使用过程中**不需要**再跑 Node 开发服务器

## 功能

- 多级分类树（叶子分类绑定本地目录）
- 项目粘贴保存，支持附件
- 同一分类 + 同一时间周期的项目合并进同一个 Word
- 每次 Word 内容变化均保存到 SQLite；本地目录只保留最新版本
- 周期文件页可查看、下载和恢复任意 Word 历史版本
- 系统设置中管理数据库备份目录、间隔、保留数量及备份文件
- 项目列表 / 周期文件 / 分类管理
- 定时自动保存草稿（防丢失）
- Word 被打开时给出明确占用提示，失败重试不重复建项目

## 日常使用

1. 安装 [Python 3.10+](https://www.python.org/downloads/)（Windows 安装时勾选 Add to PATH）
2. 启动程序：
   - Windows：双击 `start.bat`（或 `run.bat`）
   - macOS：双击 `start.command`，也可在终端运行 `./start.command`
3. 浏览器打开：`http://127.0.0.1:8765`

> 关闭启动窗口即停止服务。  
> CMD 手动启动请用 `.\start.bat`，不要直接输入 `start.bat`。
>
> 如果 macOS 提示脚本没有执行权限，请先在项目目录运行 `chmod +x start.command`。
>
> macOS 首次启动会创建 `.venv` 并联网安装 Python 依赖，之后仅在 `requirements.txt` 变化时重新安装。

## 前端技术栈（开发时）

- Vue 3 + Vite + Element Plus + Vue Router + Axios
- 源码目录：`web/`
- 构建产物：`frontend/dist/`（完整构建存在时由 FastAPI 静态托管，否则回退到 `frontend/`）

### 开发调试

```bash
# 终端 1：后端
# Windows
start.bat
# macOS
./start.command

# 终端 2：前端热更新
cd web
npm install
npm run dev
# 打开 http://127.0.0.1:5173 ，API 自动代理到 8765
```

### 改完前端后打包（只需这一次）

Windows 可双击 `build-frontend.bat`；Windows/macOS 也可在终端运行：

```bash
cd web
npm install
npm run build
```

然后使用当前平台对应的启动脚本即可。

## 目录结构

```
自己开发的文档管理系统/
├── start.bat / run.bat / start.ps1   # Windows 日常一键启动
├── start.command                     # macOS 日常一键启动
├── build-frontend.bat                # 前端打包
├── config.json
├── requirements.txt
├── backend/                          # FastAPI
├── web/                              # Vue 源码（仅开发用）
├── frontend/
│   └── dist/                         # Vue 构建产物（运行时读取）
└── data/
    ├── app.db
    └── documents/
```

## 使用说明

1. **分类管理**：建多级分类，叶子节点设置本地目录  
2. **粘贴保存**：选叶子分类 → 勾选周/月/季 → 粘贴内容 → 正式保存  
3. **项目列表**：编辑 / 删除项目  
4. **周期文件**：查看/打开合并后的 Word  

## Word 版本管理

- `data/app.db` 是 Word 历史版本的权威存储，完整 `.docx` 以 BLOB 保存。
- 分类目录中的 `.docx` 是当前版本的本地工作副本，不额外堆放历史文件。
- 项目保存、编辑或删除导致汇总内容变化时，系统自动创建新版本；重复重建不会重复留版。
- 本地最新文件缺失时，打开或下载会直接从数据库恢复。
- 检测到本地 Word 被手工修改后，下次打开或下载会先将该文件收录为新版本。
- 恢复历史版本会复制为一个新的当前版本，原历史记录保持不变。
- 恢复操作只切换 Word 文件，不回滚项目正文；项目再次变化时会继续生成新版本。

> Word 历史会增加 `app.db` 体积。备份时应完整备份 `data/app.db`；附件仍需连同分类绑定目录一起备份。

## 配置

`config.json`：

```json
{
  "host": "127.0.0.1",
  "port": 8765,
  "data_dir": "data",
  "default_docs_root": "data/documents",
  "auto_open_browser": true,
  "autosave_seconds": 30,
  "db_backup_enabled": true,
  "db_backup_dir": "data/backups",
  "db_backup_interval_hours": 24,
  "db_backup_keep": 7
}
```

数据库备份默认每 24 小时创建一次，保存在 `data/backups/`，保留最近 7 份。可在“系统设置”中修改，也可手动创建、下载或删除备份。

## 技术说明

- 后端：Python FastAPI + SQLite + python-docx
- 前端：Vue 3 + Element Plus（构建后为纯静态文件）
- 数据只落本机，不联网上传
