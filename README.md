# CULTScope

**邪典电影文化观察站 · 数据清洗与探索性可视化**

CULTScope 是一个使用 Vue 3、ECharts 和 FastAPI 构建的电影数据探索项目，包含电影数据看板、IMDb 统计和 Cult 电影知识库等页面。数据看板展示人工选定的 12 部 Cult 电影探索样本；样本不代表整体电影市场趋势或统计推断。

## 项目结构

```text
CULTScope/
├── backend/
│   ├── app/                   # FastAPI 后端
│   ├── data/                  # 数据相关文件
│   ├── scripts/               # 后端脚本
│   ├── tests/                 # 后端测试
│   └── requirements.txt       # Python 依赖
├── frontend/
│   ├── src/                   # Vue 前端
│   │   ├── components/        # 图表等组件
│   │   └── dashboard/         # 数据看板辅助模块
│   ├── tests/                 # 前端测试
│   └── package.json          # npm 依赖与脚本
├── docs/                      # 项目文档
├── .venv/                     # 本地 Python 虚拟环境（不应提交）
└── README.md
```

## 技术栈

- **前端：** Vue 3、Vite 6、ECharts 5、Axios
- **后端：** FastAPI 0.115.6、Uvicorn 0.34.0
- **数据处理：** pandas、requests 等；具体版本参见 `backend/requirements.txt`
- **测试：** 前端使用 Node.js 内置测试运行器

> 依赖版本以 `frontend/package.json` 和 `backend/requirements.txt` 为准。前端使用的 `^` 版本范围并不代表锁定的实际安装版本。

## 本地开发（Windows PowerShell）

以下命令均从 **CULTScope 项目根目录**开始执行。前后端请使用两个不同终端。

### 1. 准备 Python 虚拟环境

如果已经有可用的项目根目录 `.venv`，无需重新创建。首次搭建环境时可运行：

```powershell
py -m venv .venv
```

如果系统没有 `py` 命令，请先确认已安装并能执行的 Python 解释器路径，再使用该解释器创建虚拟环境。

使用项目虚拟环境安装后端依赖：

```powershell
& ".\.venv\Scripts\python.exe" -m pip install -r ".\backend\requirements.txt"
```

**不要默认使用** `python` 或 `D:\Anaconda\python.exe`；它们可能不是项目 `.venv` 的解释器。

检查后端环境：

```powershell
& ".\.venv\Scripts\python.exe" -c "import sys, uvicorn; print(sys.executable); print(uvicorn.__version__)"
```

### 2. 启动后端

在第一个 PowerShell 终端运行：

```powershell
cd backend
& "..\.venv\Scripts\python.exe" -m uvicorn app.main:app --reload
```

正常启动后，服务默认监听：

```text
http://127.0.0.1:8000
```

看到 `Application startup complete.` 后，保持这个终端运行。**按 `Ctrl+C` 会尝试停止后端。**

### 3. 启动前端

在第二个 PowerShell 终端，从项目根目录运行：

```powershell
cd frontend
npm install
npm run dev
```

按 Vite 终端实际输出的地址访问页面。此前本地开发使用：

```text
http://localhost:5173
```

如果端口被占用，Vite 可能选择其他端口，请以终端显示为准。

## 测试与构建

### 前端测试

在 `frontend` 目录运行：

```powershell
npm test
```

当前测试脚本运行：

- `tests/router.test.mjs`
- `tests/imdb.test.mjs`
- `tests/dashboard.test.mjs`

### 前端生产构建

在 `frontend` 目录运行：

```powershell
npm run build
```

本地预览生产构建：

```powershell
npm run preview
```

### 后端测试

后端测试位于 `backend/tests/`。正式执行方式请以项目实际测试依赖和配置为准；不要假定 `requirements.txt` 已包含 `pytest`。

## 常见问题

### `python -m uvicorn` 没有启动服务

先确认 `python` 是否指向正确的解释器。建议在 `backend` 目录使用经过验证的项目虚拟环境启动命令：

```powershell
& "..\.venv\Scripts\python.exe" -m uvicorn app.main:app --reload
```

### `ModuleNotFoundError: No module named 'uvicorn'`

通常表示当前使用的 Python 环境没有安装 Uvicorn。先运行上面的解释器检查命令，确认使用的是项目 `.venv`；需要安装依赖时，使用 `.venv` 中的 Python 执行 `pip install -r`，不要直接修改 Anaconda 基础环境。

### 端口 8000 已被占用

先只读检查监听记录：

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
    Select-Object LocalAddress, LocalPort, OwningProcess
```

再核对对应进程身份。Uvicorn 的 `--reload` 模式可能有监控进程和服务进程，**不要仅凭 PID 数字批量结束所有 Python 进程**。

### 前端显示“列表接口加载失败”

确认后端终端仍在运行，并检查 API 是否可访问。后端恢复后，可使用页面中的“重新加载”按钮再次请求列表；不要把 HTTP 500 一概视为某个固定原因。

### 构建提示 JavaScript chunk 体积较大

Vite 的 chunk 大小警告不等于构建失败。未来可单独评估路由懒加载及代码分割，避免在功能修复阶段混入性能重构。

## 开发与提交约定

建议使用小步开发流程：

1. 完成单一范围的修改。
2. 运行 `npm test` 和 `npm run build`。
3. 在必要时检查移动端布局、接口错误提示与重试流程。
4. 使用 `git diff`、`git status` 核查变更，然后精确暂存与提交。
5. 推送前确认当前分支和远端状态；不要使用强制推送作为常规操作。

**已验证基线：** CULTScope 3.5.4C，提交 `627edf5`。当次验收中，前端测试 40/40 通过、生产构建成功，320px 与 390px 移动端显示及错误重试流程完成浏览器检查。

GitHub 仓库：https://github.com/wmj05/CULTScope
