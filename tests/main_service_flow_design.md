# 主服务流程模块化设计

## 1. 设计目标

主服务部分只做流程编排，不直接实现窗口识别、MITM 捕获、HTML 解析、评论采集、离线缓存和 SQLite 写入细节。

目标是把已经在诊断工具中验证过的能力封装成可复用模块，再由主服务按顺序拼接：

- 高内聚：每个模块只负责一类明确业务能力。
- 低耦合：模块之间只通过标准数据对象通信。
- 易维护：主流程文件只描述“先做什么、后做什么”，不堆底层实现。
- 易扩展：后续新增评论、离线缓存、重试、任务队列时，不破坏主页窗口控制主线。
- 易诊断：主服务和诊断工具复用核心模块，但各自维护自己的状态展示和日志格式。

## 2. 当前约束

当前项目已有分层原则：

- `app` 只负责 API、桌面桥接和静态页面挂载。
- `services` 负责任务编排。
- `modules` 只做单一能力工具。
- `storage` 只做 SQLite 初始化和仓储读写。
- 主流程不直接解析 HTML、不直接写归档、不直接操作 MITM 内部细节。
- 系统代理和 MITM 是全局资源，同一时间只允许一个前台文章采集任务接管。
- 诊断工具已经验证过窗口点击流程、单篇详情获取、初始内容存储、评论信息、离线缓存等能力。

本设计以当前主服务页面为入口，不再以旧主流程为核心。

## 3. 推荐目录结构

建议新增主服务编排目录：

```text
src/services/main_flow/
  __init__.py
  main_flow_service.py
  main_flow_coordinator.py
  main_flow_models.py
  main_flow_state.py
  traffic_stats_aggregator.py
  home_scan_service.py
  article_dispatcher.py
  main_flow_logger.py
```

各文件职责：

- `main_flow_service.py`
  - 对外提供开始、停止、查询状态接口。
  - 由 `dev_server.py` 调用。
  - 不写具体采集流程。

- `main_flow_coordinator.py`
  - 主流程核心编排器。
  - 负责主页初始化、文章卡片循环、滚动、分发单篇任务、等待回执、收尾清理。

- `main_flow_models.py`
  - 定义主流程输入、文章目标、单篇任务选项、单篇任务回执、主流程快照等数据对象。

- `main_flow_state.py`
  - 维护当前状态、当前动作、公众号名称、任务信息、进度、活跃子进程、异常记录、取消令牌。

- `traffic_stats_aggregator.py`
  - 汇总主进程和各子进程上报的流量增量。
  - 生成当前上传、下载速率快照，不读取系统总网卡流量。
  - 流量统计属于辅助状态，统计失败不得影响采集任务。

- `home_scan_service.py`
  - 封装主页窗口定位、公众号名称读取、UIA 文章卡片解析、日期过滤、滚动读取。
  - 复用 `modules/window` 中已经调好的能力。
  - 不负责点击文章、不负责保存数据。

- `article_dispatcher.py`
  - 封装单篇任务分发。
  - 调用已有 `services/task` 中的单篇任务能力。
  - 负责把单篇任务回执转换成主流程能理解的事件。

- `main_flow_logger.py`
  - 生成用户可读运行日志。
  - 详细异常仍交给现有 runtime log/error log。

## 4. 核心数据对象

### 4.1 MainFlowCommand

前端点击“开始运行”时传入。

```text
MainFlowCommand
- target_count: int
- date_filter_mode: all | range | before | after
- start_date: date | None
- end_date: date | None
- collect_comments: bool
- archive_offline: bool
- offline_archive_mode: standard | beta
- skip_collected_records: bool
- single_task_interval_seconds: float
```

说明：

- `target_count = 0` 表示按日期边界或页面结束条件运行，不以固定数量结束。
- `skip_collected_records` 只作为选项传入单篇任务，由单篇任务内部判断是否已采集。
- 主流程不再单独查询数据库做跳过验证。

### 4.2 MainFlowContext

主流程运行时上下文。

```text
MainFlowContext
- task_id: str
- db_path: Path
- storage_root: Path
- temp_dir: Path
- config_snapshot: AppConfig
- cancel_token: Event
- started_at: datetime
- state: MainFlowState
```

说明：

- 主流程启动时读取一次内存配置快照。
- 运行过程中不直接重新读取 YAML。
- 所有模块只接收上下文或明确参数。

### 4.3 HomeArticleTarget

主页扫描出来的文章卡片目标。

```text
HomeArticleTarget
- sequence: int
- account_name: str
- article_date: str
- title_raw: str
- title_display: str
- card_rect: Rect
- visible_rect: Rect
- click_point: Point
- fingerprint: str
- source_snapshot_id: str
```

说明：

- `fingerprint` 用于本轮主页去重，建议由 `article_date + title_raw` 生成。
- 点击坐标必须来自最近一次 UIA 读取结果。
- 主流程只保存目标信息，不直接点击。

### 4.4 SingleArticleOptions

传给单篇任务的选项。

```text
SingleArticleOptions
- skip_collected_records: bool
- collect_article_detail: true
- collect_comments: bool
- archive_offline: bool
- offline_archive_mode: standard | beta
```

说明：

- `collect_article_detail` 固定为 true，对应主服务页面中锁定的“文章详情”。
- 评论和离线归档是单篇任务的后置能力。
- 跳过已采集记录由单篇任务内部完成。

### 4.5 SingleArticleReceipt

单篇任务返回给主流程的回执。

```text
SingleArticleReceipt
- task_id: str
- target_fingerprint: str
- status: success | skipped_collected | failed | cancelled
- foreground_done: bool
- tab_closed: bool
- article_saved: bool
- comments_status: pending | success | skipped | failed | not_requested
- offline_status: pending | success | skipped | failed | not_requested
- archive_dir: str | None
- article_title: str
- message: str
- error_stage: str | None
- error_detail: str | None
- duration_seconds: float
```

说明：

- `skipped_collected` 表示单篇任务判断文章已采集，未执行点击或后续采集。
- `skipped_collected` 不计入成功采集数量，也不计入异常数量。
- `foreground_done = true` 表示主页窗口可以继续下一篇。
- 如果跳过发生在点击前，可以认为 `foreground_done = true`，但 `tab_closed = false`。
- 如果点击后失败，只要文章标签已关闭，也应返回 `foreground_done = true`，避免主流程卡住。
- 如果异常导致无法确认主页可继续，主流程进入清理阶段。

## 5. 主流程状态机

建议状态：

```text
idle
starting
running
stopping
completed
failed
cancelled
```

页面展示映射：

- `idle` -> 待准备
- `starting` -> 待准备 / 正在准备
- `running` -> 运行中
- `stopping` -> 停止中
- `completed` -> 已完成
- `failed` -> 异常
- `cancelled` -> 已停止

当前动作只显示“正在xxx”，建议动作枚举：

```text
正在定位公众号主页
正在读取公众号名称
正在识别文章卡片
正在定位目标日期
正在分发单篇任务
正在等待文章标签关闭
正在滚动主页
正在等待后置任务完成
正在清理运行资源
```

## 6. 主流程执行顺序

### 6.1 启动

```text
前端点击开始运行
-> POST /api/task/start
-> MainFlowService.start(command)
-> 创建 MainFlowContext
-> 设置状态 starting
-> 启动后台主流程线程
-> 返回当前运行状态
```

### 6.2 主页初始化

```text
MainFlowCoordinator.run()
-> 状态：正在定位公众号主页
-> HomeScanService.find_home_window()
-> 状态：正在读取公众号名称
-> HomeScanService.read_account_name()
-> 写入 state.account_name
-> 初始化主页游标
```

要求：

- 找不到主页窗口，主流程失败并记录异常。
- 公众号名称只在启动后读取一次。
- 后续滚动只更新文章卡片，不重复读取公众号名称。

### 6.3 日期定位

仅在需要定位日期时执行：

- 日期范围：需要定位到范围边界。
- 起始日期：需要先定位到起始日期或第一个早于起始日期的日期组。
- 不限日期：不定位，从当前页面开始。
- 截止日期：不定位，从当前页面开始。

```text
如果需要日期定位
-> 状态：正在定位目标日期
-> HomeScanService.locate_date_boundary(command)
-> 定位阶段只读取日期组
-> 不处理日期组内文章卡片
-> 到达目标边界后进入正式收录
```

### 6.4 文章扫描

```text
状态：正在识别文章卡片
-> HomeScanService.scan_visible_targets()
-> 得到当前可视区文章卡片
-> 按日期模式过滤
-> 按本轮 fingerprint 去重
-> 得到待分发目标列表
```

注意：

- 主流程不在这里查询数据库判断是否已采集。
- 本轮内存去重仍然需要保留，防止滚动后重复分发同一张卡片。
- 如果候选为空，执行滚动。
- 如果达到日期边界或页面无法继续滚动，结束主流程。

### 6.5 单篇任务分发

```text
取一个 HomeArticleTarget
-> 状态：正在分发单篇任务
-> ArticleDispatcher.dispatch(target, options)
-> state.active_child_process_count + 1
-> state.total_child_process_count + 1
-> 状态：正在等待文章标签关闭
-> 等待 SingleArticleReceipt.foreground_done
```

交互规则：

- 单篇任务内部先执行“跳过已采集记录”判断。
- 如果单篇任务返回 `skipped_collected`：
  - 主流程记录跳过。
  - 不增加成功采集数量。
  - 不增加异常数量。
  - 不占用目标任务数量。
  - 继续寻找下一篇。
- 如果单篇任务返回 `success` 且 `article_saved = true`：
  - 主流程成功数量 +1。
  - 更新平均时长。
  - 如果后置评论/离线缓存仍在跑，继续由子任务更新状态。
- 如果单篇任务返回 `failed`：
  - 异常记录 +1。
  - 该文章任务视为已处理，不重复点击同一文章。
  - 主流程继续下一篇，除非错误属于全局资源不可恢复。
- 如果单篇任务返回 `cancelled`：
  - 主流程进入停止或清理。
- 如果单篇任务没有返回 `foreground_done`：
  - 主流程进入清理，避免继续点击造成窗口错乱。

### 6.6 滚动继续

```text
当前可视区有效目标处理完
-> 状态：正在滚动主页
-> HomeScanService.scroll_next()
-> 滚动后重新读取 UIA
-> 使用上次最后文章 fingerprint 对齐
-> 继续扫描后续文章
```

要求：

- 滚动逻辑只属于 `HomeScanService`。
- 主流程不直接调用鼠标或 UIA 底层 API。
- 如果懒加载后无新内容，需要由 `HomeScanService` 内部做回弹滚动和重试。
- 主流程只关心结果：有新卡片、无新卡片、滚动失败、到达边界。

### 6.7 完成与收尾

```text
达到目标数量 / 达到日期边界 / 页面结束 / 用户停止
-> 状态：正在清理运行资源
-> 等待必要前台任务结束
-> 停止不再分发新任务
-> 检查代理和 MITM 是否残留
-> 检查文章详情标签是否残留
-> 输出最终状态
```

如果评论和离线缓存是后置并发任务，可以支持两种策略：

- 策略 A：主流程完成分发后等待后置任务全部完成，再显示已完成。
- 策略 B：主流程完成前台采集后显示“后置处理中”，等后置任务结束再显示已完成。

推荐第一阶段使用策略 A，状态更直观。

## 7. 跳过已采集记录的交互设计

你已确认“跳过已采集记录”封装在单篇任务流程中，因此主流程不再单独验证数据库。

交互方式如下：

```text
主流程
-> 分发 HomeArticleTarget + SingleArticleOptions.skip_collected_records
-> 单篇任务内部判断是否已采集
-> 单篇任务返回 SingleArticleReceipt.status
-> 主流程根据 receipt.status 决定是否计数
```

单篇任务内部建议：

```text
if skip_collected_records:
    根据公众号名称、日期、标题原文归一化后查询
    if 已采集:
        return SingleArticleReceipt(
            status='skipped_collected',
            foreground_done=True,
            tab_closed=False,
            article_saved=False,
            message='已采集，跳过'
        )

继续执行正式采集
```

主流程处理建议：

```text
if receipt.status == 'skipped_collected':
    skipped_collected_count += 1
    handled_fingerprints.add(target.fingerprint)
    不增加 completed_count
    不增加 error_count
    继续下一篇
```

这样可以满足：

- 跳过记录不占用任务数量。
- 主流程不重复实现数据库查询。
- 单篇任务仍是唯一的采集入口。
- 后续修改已采集判断规则，只改单篇任务。

## 8. 进度口径

建议主服务页面使用以下口径：

- 采集进度：`成功保存文章详情数量 / 目标数量`
- 跳过已采集：单独记录在日志或任务统计中，不算分子。
- 异常记录：单篇任务任一关键节点失败时 +1。
- 活跃子进程：`当前运行中子进程 / 累计启动过子进程`
- 平均时长：已完成文章详情保存的单篇总耗时平均值；如果文章详情成功但评论失败，仍计入平均时长。

如果 `target_count = 0`，页面可以显示：

```text
已完成数量 / 全部
```

或：

```text
已完成数量 / 日期边界
```

### 8.1 当前速率口径

“当前速率”只用于展示本程序采集过程中的大概网络活动，不代表电脑总网速，也不追求 TCP/IP 层面的精确计量。

前端只显示总上传和总下载：

```text
↑ 12.4 KB/s
↓ 386.7 KB/s
```

不增加“低速、正常、高速”等文字状态。无流量数据时显示 `0 KB/s`。建议 tooltip 使用：

```text
按本程序内部记录的请求、响应和资源保存字节估算，不代表系统总网速。
```

各模块只上报自己能够确认的字节增量，不直接修改页面状态：

- MITM：上报捕获到的请求和响应字节数。
- HTML/reference 请求：上报请求字节和 `len(response.content)`。
- 评论采集：上报评论接口请求、响应以及实际保存的评论资源字节数。
- 离线缓存：上报 Playwright 捕获并最终保存到 `assets` 的资源字节数。
- 其他没有可靠字节数据的步骤不上报，不使用虚构值补齐。

统一流量增量事件：

```text
NetworkTrafficDelta
- task_id: str
- article_task_id: str | None
- source: mitm | html_request | comments | offline_cache
- upload_bytes: int
- download_bytes: int
- timestamp: datetime
```

同一进程内可以直接调用汇总器；MITM、评论和离线缓存等子进程通过现有进程通信通道上报可序列化事件。主流程只接收和汇总，不轮询系统网卡，也不读取其他程序的流量。

建议由独立汇总器维护统计：

```text
TrafficStatsAggregator
- append(delta)
- snapshot()
- reset()
```

统计与展示节奏：

- 子进程内部按 `100ms` 时间桶合并增量，避免每个响应分片都发送一条消息。
- 主流程汇总最近 `2 秒` 的增量并计算滑动平均，减少瞬时跳动。
- 前端约每 `1 秒` 读取一次状态快照，不要求跟随每个 `100ms` 桶刷新页面。
- 主流程停止、完成或异常清理后调用 `reset()`，当前速率恢复为 `0 KB/s`。

`MainFlowState` 保存最近一次速率快照，`GET /api/task/status` 中的 `MainFlowSnapshot` 增加：

```text
traffic:
  uploadRateBytesPerSecond: int
  downloadRateBytesPerSecond: int
  updatedAt: datetime | None
  sourceBreakdown:
    mitm: { uploadBytes, downloadBytes }
    html_request: { uploadBytes, downloadBytes }
    comments: { uploadBytes, downloadBytes }
    offline_cache: { uploadBytes, downloadBytes }
```

第一阶段前端只展示 `uploadRateBytesPerSecond` 和 `downloadRateBytesPerSecond`；`sourceBreakdown` 先保留给诊断和后续扩展，不在主服务页面展开。流量事件丢失、反序列化失败或统计异常只写详细日志，不能将单篇任务或主流程标记为失败。

## 9. 日志设计

页面运行日志保持简单：

```text
[INFO] 开始主流程：目标 20 篇，评论信息=开，离线归档=关
[INFO] 已识别公众号：人民日报
[INFO] 正在识别文章卡片：当前屏 6 篇
[SUCCESS] 文章详情保存成功：标题...
[INFO] 已采集，跳过：标题...
[WARN] 评论采集失败：标题...
[ERROR] 单篇任务失败：标题...，阶段=mitm_capture
[INFO] 正在清理运行资源
```

详细异常写入实际 log 文件，不在页面塞长堆栈。

## 10. API 建议

### 10.1 开始运行

```text
POST /api/task/start
body: MainFlowCommand
return: MainFlowSnapshot
```

### 10.2 停止运行

```text
POST /api/task/stop
return: MainFlowSnapshot
```

### 10.3 查询状态

```text
GET /api/task/status
return: MainFlowSnapshot
```

其中 `MainFlowSnapshot.traffic` 使用第 8.1 节定义的结构。速率字段统一返回每秒字节数，由前端换算成 `B/s`、`KB/s` 或 `MB/s`，避免后端和前端使用不同换算规则。

### 10.4 查询日志

```text
GET /api/task/logs?limit=100
return: SummaryLog[]
```

可以保留现有前端接口路径，后端实现替换为新的 `MainFlowService`。

## 11. 与现有诊断工具的关系

诊断工具和主服务共享核心能力，但不要互相调用页面逻辑。

推荐关系：

```text
modules/window, modules/proxy, modules/request, modules/archive
        ↓
services/task 单篇任务能力
        ↓
services/main_flow 主服务编排
        ↓
dev_server.py API
        ↓
vue-project 主服务页面
```

诊断工具可以继续调用：

```text
services/task/window_click_flow_huey_service.py
services/task/single_article_detail_huey_service.py
services/task/initial_content_storage_huey_service.py
services/task/article_detail_comments_huey_service.py
services/task/article_detail_offline_cache_huey_service.py
```

主服务不要直接复用诊断弹窗输出格式，只复用核心服务和数据对象。

## 12. 异常处理原则

- 找不到主页窗口：主流程失败，提示用户打开公众号主页。
- 公众号名称读取失败：主流程失败，不继续采集。
- 单篇任务跳过已采集：不是异常。
- 单篇任务采集失败：记录异常，该文章视为已处理，不重复点击。
- MITM 或系统代理异常：必须进入清理，确认代理恢复后再决定是否继续。
- 文章标签无法确认关闭：停止主流程并清理，避免误点下一篇。
- SQLite 写入失败：保留本地证据文件，记录异常，后续人工排查。
- 用户停止：不再分发新任务，等待当前前台任务到安全点后清理。

## 13. 测试建议

### 13.1 单元测试

建议新增测试：

- `test_main_flow_models.py`
  - 测试命令参数、状态快照、回执对象序列化。

- `test_main_flow_state.py`
  - 测试进度、异常数、跳过数、子进程数更新。

- `test_traffic_stats_aggregator.py`
  - 测试 `100ms` 增量桶、最近 `2 秒` 滑动平均、不同来源合并和任务结束清零。
  - 测试异常流量事件只记录日志，不影响主流程状态。

- `test_article_dispatcher_receipt.py`
  - 测试 `success`、`skipped_collected`、`failed`、`cancelled` 回执对主流程计数的影响。

- `test_home_scan_service_date_filter.py`
  - 测试不限日期、日期范围、截止日期、起始日期的筛选结果。

### 13.2 集成测试

建议用 fake 模块模拟：

- fake home scanner：返回固定文章卡片。
- fake dispatcher：按标题返回成功、跳过、失败。
- fake state store：记录状态变化。

覆盖场景：

- 目标 3 篇，全部成功。
- 中间 1 篇已采集跳过，不占目标数量。
- 单篇失败后不重复点击同一 fingerprint。
- 用户停止后不再分发新任务。
- 日期边界结束。
- 无新内容滚动结束。

### 13.3 手动验证

第一阶段手动验证：

1. 打开公众号主页。
2. 设置任务数 1。
3. 勾选评论信息，关闭离线归档。
4. 点击开始运行。
5. 确认状态变化：读取主页 -> 识别卡片 -> 分发单篇 -> 等待标签关闭 -> 保存成功 -> 清理。
6. 再测试已采集文章，确认返回跳过且不占任务数量。

## 14. 分阶段实现建议

### 阶段一：主流程骨架

- 新增 `services/main_flow`。
- 接入 `/api/task/start`、`/api/task/stop`、`/api/task/status`。
- 使用 fake dispatcher 跑通状态和日志。

### 阶段二：主页扫描接入

- 抽取当前窗口点击流程中的主页扫描核心。
- 接入公众号名称、文章卡片、日期筛选、滚动。
- 暂不真实点击文章。

### 阶段三：单篇任务接入

- 接入已有单篇任务。
- 主流程等待 `foreground_done` 回执。
- 支持 `skipped_collected` 不占任务数量。

### 阶段四：评论与离线缓存接入

- 评论和离线缓存作为单篇任务后置能力。
- 控制并发数。
- 写入状态和日志。

### 阶段五：收尾与容错

- 完善停止按钮。
- 完善代理残留清理。
- 完善异常记录和日志文件。
- 补齐自动化测试。

## 15. 推荐优先级

第一优先级：

- `MainFlowCommand`
- `MainFlowState`
- `SingleArticleReceipt`
- `MainFlowCoordinator`
- fake dispatcher 测试

第二优先级：

- 主页扫描服务接入真实 UIA 模块。
- 单篇任务接入真实 Huey 服务。

第三优先级：

- 评论与离线缓存并发。
- 更细的日志和子进程状态。

## 16. 关键结论

主服务不要重新实现诊断工具已经验证过的能力，也不要直接调用底层模块堆业务逻辑。

推荐最终形态是：

```text
主服务页面
-> dev_server.py 路由
-> MainFlowService
-> MainFlowCoordinator
-> HomeScanService + ArticleDispatcher
-> services/task 单篇任务
-> modules/window/proxy/request/archive/storage
```

其中“跳过已采集记录”由单篇任务内部判断，并通过 `SingleArticleReceipt.status = skipped_collected` 告诉主流程。主流程只负责根据回执更新进度和继续分发下一篇。
