# 最小 pywebview + FastAPI + mitmproxy 运行链路

## 当前结论

当前项目的桌面端链路为：

```text
pywebview UI
  -> FastAPI 直接提供 index.html、静态资源和 /api
  -> WebviewApi
  -> TaskManager
  -> ProcessManager
  -> mitm worker
```

`main.py` 保持为 pywebview 启动入口，真实代码在 `src/app/`。

## 模块位置

- `src/app/fastapi_app/`：FastAPI 应用、路由和嵌入式 uvicorn 服务。
- `src/app/pywebview_app/webview_api.py`：暴露给 Vue / FastAPI 复用的本地业务 API。
- `src/app/fastapi_app/`：同时提供 `/api` 业务接口和 `src/webview` 静态页面。
- `src/app/pywebview_app/webview_server.py`：旧静态服务兼容实现，保留为 fallback，不再作为默认桌面链路。
- `src/webview/`：Vue 构建后的静态页面。
- `data/custom.yaml`：用户可修改的运行配置。
- `src/core/task_manager.py`：任务总控，负责启动、停止、状态和日志。
- `src/core/process_manager.py`：后台 worker 进程管理。
- `src/core/file_logger.py`：把本次启动后的界面运行日志持续追加到同一个本地 `.log` 文件。
- `src/modules/proxy/system_proxy.py`：Windows 系统代理注册表读写入口。
- `src/modules/proxy/proxy_manager.py`：保存原代理状态并负责恢复，是当前代理控制模块的一部分。
- `src/workers/mitm_worker.py`：mitmproxy worker，捕获微信文章相关请求。
- `src/modules/storage/sqlite_store.py`：SQLite 存储。
- `data/awa_public.sqlite3`：SQLite 数据库文件。

## 运行方式

安装依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

构建 Vue 静态页面：

```powershell
cd D:\a_personal\Github-240809_Access_wechat_article\vue-project
npm run build
```

启动桌面应用：

```powershell
cd D:\a_personal\Github-240809_Access_wechat_article
.\.venv\Scripts\python.exe main.py
```

只启动 FastAPI 后端服务：

```powershell
.\.venv\Scripts\python.exe dev_server.py
```

后端默认地址：

```text
http://127.0.0.1:8766
```

API 文档地址：

```text
http://127.0.0.1:8766/docs
```

## 数据库表

当前 SQLite 只使用两张 AWA 表：

- `awa_public_accounts`：公众号信息，字段为 `id`、`account_name`、`created_time`、`updated_time`。
- `awa_public_articles`：文章信息，字段为 `id`、`account_id`、`article_title`、`published_article_time`、`article_link`、`record_type`、`collect_time`、`duration_seconds`、`collect_status`。

不会把 `key`、`pass_ticket`、`appmsg_token`、`uin` 等临时 token 写入 SQLite。

## 验证命令

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
.\.venv\Scripts\python.exe -m compileall -q main.py dev_server.py app src tests
```

真实 mitm smoke test 会短暂修改系统代理，只有需要验证代理链路时再手动运行：

```powershell
.\.venv\Scripts\python.exe tests\smoke_task_manager.py
```
