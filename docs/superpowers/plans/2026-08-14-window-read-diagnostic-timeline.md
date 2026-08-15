# Window Read Diagnostic Timeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在窗口测试弹窗中实时顺序展示主页读取、候选判定、滚动和文章结果，并修复有可靠边界但部分标题行无坐标时的漏读。

**Architecture:** 读取器返回候选判定元数据，游标通过可选事件回调上报读取、滚动与稳定检测，诊断服务合并为有序时间线。前端根据事件 `kind/tone` 渲染紧凑操作行、警告行和文章详情，主采集流程在未传事件回调时行为不变。

**Tech Stack:** Python 3.13、uiautomation、FastAPI 诊断任务、Vue 3、TypeScript、VXE UI、unittest、Node test runner。

---

### Task 1: 候选判定元数据与漏读修复

**Files:**
- Modify: `src/modules/window/article_card_reader.py`
- Test: `tests/test_window_article_date_filter.py`

- [ ] 写失败测试：有可见日期和完整阅读指标时，无坐标标题行不应导致整篇文章被丢弃。
- [ ] 写失败测试：无边界标题残片、指标矩形不完整和过渡帧分别返回可读的丢弃原因。
- [ ] 运行 `uv run python -m unittest tests.test_window_article_date_filter`，确认新增测试因缺少判定元数据而失败。
- [ ] 为 `ArticleViewportObservation` 增加范围数量和候选判定结果，并最小调整边界规则。
- [ ] 再次运行测试，确认日期分组、弱标题和视口裁切行为全部通过。

### Task 2: 游标操作事件

**Files:**
- Modify: `src/modules/window/home_article_cursor.py`
- Modify: `src/modules/window/wechat_home_scroller.py`
- Modify: `src/services/capture/window_runtime_factory.py`
- Test: `tests/test_home_article_cursor.py`
- Test: `tests/test_wechat_home_scroller.py`

- [ ] 写失败测试：首次读取、内容变化读取、滚动发送和稳定检测按顺序上报事件。
- [ ] 写失败测试：重复轮询快照不重复生成读取事件，滚动事件包含方向和实际步数。
- [ ] 运行相关测试并确认失败原因来自事件接口尚未实现。
- [ ] 给游标增加可选 `trace` 回调，给滚动器暴露只读默认步数，并由运行时工厂透传。
- [ ] 运行相关测试并确认主流程无回调时保持原行为。

### Task 3: 服务层统一时间线

**Files:**
- Modify: `src/services/runtime/window_click_flow_diagnostic_service.py`
- Test: `tests/test_window_article_date_filter.py`

- [ ] 写失败测试：操作事件、丢弃候选、日期跳过和文章结果按发生顺序进入 `items/events`。
- [ ] 写失败测试：丢弃事件包含标题片段、日期、阅读指标和原因。
- [ ] 运行服务测试并确认旧 payload 只有摘要和文章结果。
- [ ] 实现有序事件列表、事件去重和实时 `publish()`，保留现有 `records` 兼容字段。
- [ ] 运行服务测试并确认停止、日期边界和异常返回也保留已产生的时间线。

### Task 4: 前端时间线展示

**Files:**
- Modify: `vue-project/src/bridge/pythonApi.ts`
- Modify: `vue-project/src/pages/SettingsPage.vue`
- Test: `vue-project/src/__tests__/windowClickFlowDateFilter.test.ts`
- Test: `vue-project/src/__tests__/settingsThreePaneLayout.test.ts`

- [ ] 写失败测试：诊断条目支持 `kind/tone`，操作和丢弃候选具有独立样式类。
- [ ] 写失败测试：列表实时追加时默认跟随底部，用户上滚后停止强制跟随。
- [ ] 运行 `pnpm test` 中相关测试并确认失败。
- [ ] 扩展 TypeScript 类型、条目 class 和紧凑时间线样式，不改变弹窗整体高度。
- [ ] 运行相关前端测试和 `pnpm type-check`。

### Task 5: 综合验证

**Files:**
- Verify only: all files above

- [ ] 运行 `uv run python -m unittest tests.test_home_article_cursor tests.test_window_article_date_filter tests.test_wechat_home_scroller`。
- [ ] 运行 `uv run python -m py_compile` 检查改动的 Python 文件。
- [ ] 运行前端相关测试和 `pnpm type-check`。
- [ ] 运行 `git diff --check`，确认没有空白错误；不启动或重启用户服务。

