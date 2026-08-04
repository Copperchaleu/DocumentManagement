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
- 同一叶子分类 + 同一时间周期的项目合并进同一个 Word
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

## 配置

`config.json`：

```json
{
  "host": "127.0.0.1",
  "port": 8765,
  "data_dir": "data",
  "default_docs_root": "data/documents",
  "auto_open_browser": true,
  "autosave_seconds": 30
}
```

## 技术说明

- 后端：Python FastAPI + SQLite + python-docx
- 前端：Vue 3 + Element Plus（构建后为纯静态文件）
- 数据只落本机，不联网上传
