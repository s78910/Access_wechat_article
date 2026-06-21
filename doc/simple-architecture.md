# 简单架构说明

## 结论

当前项目采用“页面入口、业务服务、任务调度、执行 worker、业务模块、运行数据”这几层来组织代码。这个结构不是复杂的企业级架构，目标是让后续维护时可以快速判断：一个功能应该放在哪里，一个问题应该从哪里开始查。

## 目录职责

```text
src/
  app/
    fastapi_app/       后端 HTTP 接口，给 Vue 页面调用
    pywebview_app/     桌面窗口和 pywebview 相关代码

  core/                任务总调度、多进程生命周期、事件结构、任务上下文
  services/            业务服务入口，表达用户要做什么
  workers/             真正执行动作的后台任务
  modules/             可替换业务能力：代理、窗口、详情、正文、存储、系统、工具
  config/              配置读取代码
  webview/             Vue 构建后的静态页面

data/
  custom.yaml          用户运行配置
  awa_public.sqlite3   SQLite 数据库
  logs/                运行日志
  tmp/                 临时文件
```

## 启动入口

- `main.py`：正式桌面软件入口，只负责启动 pywebview 窗口、本地静态服务和内嵌 FastAPI。
- `dev_server.py`：开发阶段后端入口，只启动 FastAPI，不打开桌面窗口，方便 Chrome/Vite 调试。
- `vue-project/`：Vue 前端源码，修改页面时先改这里，再执行 `npm run build` 输出到 `src/webview/`。

## 点击“开始运行”后的主流程

```text
Vue 页面
  -> FastAPI /api/task/start
  -> src/app/fastapi_app/app.py
  -> src/app/pywebview_app/webview_api.py
  -> src/services/task_service.py
  -> src/core/task_manager.py
  -> src/workers/article_capture.py
  -> src/modules/*
  -> MITM / 微信窗口 / 文章详情 / 评论详情 / SQLite / 本地归档
```

简单理解：

- `fastapi_app` 负责接收页面请求。
- `webview_api.py` 是当前前端和 Python 业务之间的统一桥。
- `TaskService` 是新的业务入口，先把“开始任务、停止任务、读取状态、读取日志”收拢起来。
- `TaskManager` 目前仍是旧核心调度器，暂时保留，避免一次重构影响采集稳定性。
- `workers` 负责实际执行，例如点击微信文章、等待 MITM 数据、解析文章信息。
- `modules` 负责具体能力，例如代理控制、窗口控制、详情解析、存储写入。

## 新增功能应该放哪里

- 新增页面接口：优先改 `src/app/fastapi_app/app.py`。
- 新增桌面壳专用能力：优先改 `src/app/pywebview_app/webview_api.py`。
- 新增采集流程入口：优先加到 `src/services/`。
- 新增实际执行逻辑：优先加到 `src/workers/`。
- 新增文章详情或评论详情解析：优先加到 `src/modules/detail/`。
- 新增正文和资源获取：优先加到 `src/modules/content/` 和 `src/workers/body_worker.py`。
- 新增数据库读写：优先改 `src/modules/storage/sqlite_store.py` 和 `src/modules/storage/awa_public_schema.sql`。
- 新增本地文件归档：优先改 `src/modules/storage/archive_store.py` 和 `src/modules/storage/path_builder.py`。
- 新增文件、时间、文本等通用函数：优先放到 `src/modules/utils/`。
- 新增系统检测：优先放到 `src/modules/system/`。
- 修改运行参数：优先改 `data/custom.yaml` 或 `src/config/runtime_config.py`。

## 排查问题时先看哪里

- 页面按钮无反应：先看 Vue 控制台和 `src/app/fastapi_app/app.py` 的接口路径。
- API 报错：看 `src/app/pywebview_app/webview_api.py` 是否捕获并写入日志。
- 任务一直运行或停止不了：看 `src/services/task_service.py` 和 `src/core/task_manager.py`。
- MITM 抓不到请求：看 `src/workers/mitm_worker.py` 和 `src/modules/proxy/`。
- 微信窗口识别或点击异常：看 `src/modules/window/` 和对应 `src/workers/`。
- 文章详情字段不对：看 `src/modules/detail/article_detail.py` 和 `src/workers/article_capture.py`。
- 评论数据不对：看 `src/modules/detail/comment_detail.py`。
- SQLite 写入不对：看 `src/modules/storage/sqlite_store.py`。
- 本地目录名不对：看 `src/modules/storage/path_builder.py` 和 `src/modules/utils/`。

## 当前迁移原则

当前不要把 `TaskManager`、`article_capture.py`、`mitm_worker.py` 一次性拆完。它们已经包含较多跑通过的旧流程，后续应按功能逐步迁移：

1. 先在 `services/` 里新增清晰入口。
2. 再把具体执行逻辑移到对应 `workers/` 或 `modules/`。
3. 每迁移一小块就补测试。
4. 测试通过后再删旧入口。

这种做法慢一点，但更稳，适合当前项目还在持续试验 MITM、微信窗口和文章数据规则的阶段。
