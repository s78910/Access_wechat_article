# PROJECT.md

## 项目背景

Access WeChat Article 是一个面向科研材料整理场景的 Windows 桌面辅助工具，用于采集、整理和归档微信公众号公开文章的元数据与本地离线材料。项目强调本地运行、结构化记录、可复核和后续分析准备。

## 技术栈

- Python `>=3.13`
- FastAPI 本地后端服务
- pywebview / WebView2 桌面壳
- SQLite 本地数据存储
- mitmproxy 网络请求捕获
- Playwright 离线页面缓存
- Vue3 + Vite 前端工程位于 `vue-project/`
- 依赖管理使用 `uv`

## 主要入口

- `main.py`：桌面程序启动入口，会启动 FastAPI 服务并打开 pywebview 窗口。
- `dev_server.py`：开发调试入口，只启动 FastAPI 后端服务，不打开 pywebview 窗口。
- `src/app/fastapi_app/`：FastAPI 服务代码。
- `src/app/pywebview_app/`：桌面壳、窗口能力和原生 API。

## 主要目录

- `src/core/`：运行配置、任务调度、多进程生命周期、日志和任务状态。
- `src/config/`：用户运行配置读取和保存逻辑。
- `src/services/`：业务服务入口。
- `src/workers/`：后台 worker，例如抓包、文章采集和离线缓存。
- `src/modules/`：可替换业务能力模块，包括代理、窗口识别、文章详情、内容处理、存储、系统能力、HTML 归档和工具能力。
- `src/webview/`：Vue 构建后的静态页面，用于桌面壳或 FastAPI 静态加载。
- `vue-project/`：本地 Vue3 + Vite 前端开发工程。
- `doc/`：项目说明、安装说明、功能说明、架构和排查文档。
- `tests/`：自动化测试、验证脚本和测试产物。
- `data/`：运行时数据、用户配置、SQLite 数据库、日志和临时文件。
- `storages/`：文章本地归档内容。

## 运行方式

安装依赖：

```bash
uv sync
```

启动桌面程序：

```bash
uv run python main.py
```

仅启动开发后端：

```bash
uv run python dev_server.py
```

FastAPI 默认地址：

```text
http://127.0.0.1:8766
```

API 文档默认地址：

```text
http://127.0.0.1:8766/docs
```

## 数据与运行文件

- 用户配置文件：`data/custom.yaml`
- 默认 SQLite 数据库：`data/awa_public.sqlite3`
- 日志目录：`data/logs/`
- 临时目录：`data/tmp/`
- MITM 配置与证书目录：`.mitmproxy/`
- Playwright 浏览器目录：`.playwright-browsers/`
- 本地文章归档目录：`storages/`

## 待确认

- 公开发布前的 README 中文文本编码显示需要在编辑器或 GitHub 页面中再次确认。
- 当前仓库是否需要提交 `vue-project/` 源码，按 `AGENTS.md` 规则默认为不提交，除非用户明确要求。
