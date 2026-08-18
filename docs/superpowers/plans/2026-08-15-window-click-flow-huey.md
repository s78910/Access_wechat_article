# Window Click Flow Huey Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 使用 SqliteHuey 执行现有窗口点击流程诊断，并保持内存状态、协作停止和前端 API 合同不变。

**Architecture:** 新增一个应用内 `WindowClickFlowHueyService`，拥有会话级 SQLite 队列、单线程 consumer、任务字典和停止事件。FastAPI 入口只调用服务的 `start/get/stop`，退出阶段调用 `shutdown`；现有 `WindowClickFlowDiagnosticService` 不改。

**Tech Stack:** Python 3.13、Huey 3.3.4、SQLite、FastAPI、unittest。

---

### Task 1: Huey窗口诊断服务

**Files:**
- Create: `src/services/task/window_click_flow_huey_service.py`
- Create: `tests/test_window_click_flow_huey_service.py`

- [x] 编写失败测试，覆盖真实 SqliteHuey 入队执行、四张 Huey 表、会话级队列路径、实时更新、停止和并发冲突。
- [x] 运行 `uv run python -m unittest tests.test_window_click_flow_huey_service`，确认因服务不存在而失败。
- [x] 实现单 worker 内嵌 consumer、内存任务字典、`Event` 停止和现有窗口诊断 Service 调用。
- [x] 重跑该测试并确认通过。

### Task 2: FastAPI入口接入

**Files:**
- Modify: `dev_server.py`
- Modify: `tests/test_window_article_date_filter.py`

- [x] 修改现有入口测试，要求启动接口调用 Huey 服务而不是创建 `Thread`。
- [x] 运行相关测试确认旧实现不满足新断言。
- [x] 在 `DevBackendContext` 中装配 Huey 服务，将 start/get/stop 路由改为服务转发，并在 `shutdown_backend` 中关闭 consumer。
- [x] 删除窗口测试专用 `Thread` runner 和旧内存字段，保留测试 runner 注入能力于新服务构造参数。
- [x] 重跑窗口筛选和API相关测试。

### Task 3: 回归验证

**Files:**
- Verify: `src/services/runtime/window_click_flow_diagnostic_service.py`
- Verify: `vue-project/src/pages/SettingsPage.vue`

- [x] 运行窗口读取、日期筛选、滚动和API回归测试。
- [x] 运行 `uv run python -m compileall src dev_server.py`。
- [x] 检查工作树差异，确认未修改现有窗口算法和Vue页面。
