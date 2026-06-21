# pywebview、FastAPI 与前端架构笔记

## 当前结论

项目现在采用“FastAPI 后端 + Vue 前端 + pywebview 桌面壳”的结构。开发阶段可以直接用 Chrome 打开 Vite 页面，正式桌面运行时由 pywebview 加载构建后的静态页面。

## 目录边界

```text
src/app/fastapi_app/
  FastAPI 应用、路由和嵌入式 uvicorn 服务

src/app/pywebview_app/
  pywebview 桌面壳、WebviewApi、窗口尺寸工具，以及旧静态服务 fallback

src/webview/
  Vue 构建后的静态页面，供 pywebview 加载

vue-project/
  Vue3 + TypeScript + Vite 前端源码
```

根目录 `app/` 兼容转发层已删除；后续代码统一从 `src.app.fastapi_app` 或 `src.app.pywebview_app` 导入。

## 运行链路

### Chrome/Vite 开发模式

```text
Chrome
  -> http://localhost:5173/
  -> Vite proxy /api
  -> FastAPI http://127.0.0.1:8766
  -> WebviewApi
  -> TaskManager / MITM / SQLite / 本地文件
```

独立后端启动命令：

```bash
.\.venv\Scripts\python.exe dev_server.py
```

### pywebview 桌面模式

```text
main.py
  -> WebviewApi
  -> FastApiServer 127.0.0.1:8766
  -> FastAPI 挂载 src/webview 静态页面
  -> pywebview 加载 http://127.0.0.1:8766/index.html
  -> 前端同源调用 /api
```

桌面启动命令：

```bash
.\.venv\Scripts\python.exe main.py
```

## 前端构建约定

`vue-project/vite.config.ts` 中应保持：

```ts
base: './',
build: {
  outDir: '../src/webview',
  emptyOutDir: true,
}
```

构建命令：

```bash
cd D:\a_personal\Github-240809_Access_wechat_article\vue-project
npm run build
```

构建完成后必须确认 `src/webview/index.html` 中没有 `impeccable-live-start` 或 `localhost:8400/live.js`。

## 接口边界

- 业务 API 统一通过 FastAPI `/api/...` 暴露。
- Vue 页面业务调用统一走 `vue-project/src/bridge/pythonApi.ts`。
- `window.pywebview.api` 只保留桌面壳特有能力，例如窗口尺寸调整。
- 现阶段 FastAPI 路由复用 `WebviewApi`，避免重复实现 TaskManager 调用逻辑；后续可逐步抽服务层。
- pywebview 默认不再启动独立 `8765` 静态服务，减少一层 `/api` 转发和一处端口占用。

## 后续演进建议

- 把 `WebviewApi` 中与业务无关的桌面能力和业务 API 能力继续拆分。
- 为 FastAPI 请求和响应逐步补 Pydantic 模型。
- 保持入口直接导入 `src.app...`，不要再新增根目录 `app/` 兼容层。
- 保持 MITM、系统代理、SQLite 和本地归档逻辑在 `src/core`、`src/workers`、`src/modules/*` 等业务目录中，不要混入前端壳代码。
