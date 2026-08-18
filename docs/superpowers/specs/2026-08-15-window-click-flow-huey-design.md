# 窗口点击流程 Huey 封装设计

## 目标

将诊断工具“窗口点击流程”的后台执行方式从直接创建 `Thread` 改为 `SqliteHuey` 入队和单线程 consumer 执行，同时保持现有 UIA 读取、日期定位、滚动、前端轮询和诊断文件格式不变。

## 边界

- Huey 只负责任务排队和执行，不保存前端实时状态。
- 实时状态继续使用进程内字典，停止继续使用 `Event`。
- 每次后端启动使用独立的会话级 SQLite 队列文件，旧诊断任务不会跨启动恢复。
- 队列数据库位于 `data/tmp/huey/window-click-flow-<session_id>.sqlite3`。
- consumer 使用一个 `thread` worker，不允许两个窗口测试并行操作同一微信主页。
- 完整过程继续写入 `data/tmp/window-click-flow/<job_id>/execution.jsonl`，最终结果写入同目录 `result.json`。

## 组件

新增 `WindowClickFlowHueyService`，负责：

- 创建会话级 `SqliteHuey` 和内嵌 thread consumer。
- 创建、查询、停止和裁剪窗口诊断任务。
- 保存内存状态字典与停止事件。
- 调用现有 `WindowClickFlowDiagnosticService`。
- 后端退出时请求停止活动任务并关闭 consumer。

`dev_server.py` 只负责将现有三个 HTTP 接口转发给该服务，并在后端启动和关闭时装配、释放服务。

## 状态与停止

前端继续识别 `running` 和 `stop-requested` 为实时状态。停止请求先设置 `Event`，任务在进入窗口操作前和现有循环检查点协作退出。服务端同一时间只允许一个窗口测试；重复提交返回冲突。

## 数据

Huey 任务只传递 `job_id`、数量和日期筛选参数。UIA 控件、窗口对象、锁、`Event`、配置对象和 Service 实例均不进入 SQLite BLOB。Huey 任务返回 `None`，完整结果只保存于内存状态和诊断 JSON，避免重复占用队列数据库。
