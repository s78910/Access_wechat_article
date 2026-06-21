# pywebview + Vue 最小运行说明

## 当前运行链路

当前桌面端运行链路为：

```text
src/webview 静态页面
  -> pywebview 桌面窗口
  -> FastAPI 同源加载页面和 /api 接口
  -> WebviewApi / TaskManager
```

根目录 `main.py` 只作为 pywebview 启动入口，真实实现位于 `src/app/`。

## 构建 Vue 静态页面

```bash
cd D:\a_personal\Github-240809_Access_wechat_article\vue-project
npm run build
```

构建产物输出到：

```text
D:\a_personal\Github-240809_Access_wechat_article\src\webview
```

其中入口文件为：

```text
src/webview/index.html
```

## 启动桌面应用

```bash
cd D:\a_personal\Github-240809_Access_wechat_article
.\.venv\Scripts\python.exe main.py
```

启动流程：

1. Python 检查 `src/webview/index.html` 是否存在。
2. 启动 FastAPI 服务，默认地址为 `127.0.0.1:8766`。
3. FastAPI 挂载 `src/webview` 静态页面和 `/api/...` 业务接口。
4. pywebview 打开 `http://127.0.0.1:8766/index.html`。
5. 页面业务请求继续调用同源 `/api/...`。

## 启动独立后端服务

如果只想用 Chrome/Vite 调试前端，不打开 pywebview，运行：

```bash
cd D:\a_personal\Github-240809_Access_wechat_article
.\.venv\Scripts\python.exe dev_server.py
```

后端服务地址：

```text
http://127.0.0.1:8766
```

API 文档地址：

```text
http://127.0.0.1:8766/docs
```

前端开发页默认地址：

```text
http://localhost:5173/
```
