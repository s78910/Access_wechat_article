# Window Date Seek Scroll Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让诊断工具“窗口点击流程”在日期定位阶段按日期距离使用最大 18 步的自适应滚动，并在每次滚动后完整等待懒加载周期。

**Architecture:** `WindowClickFlowDiagnosticService` 继续负责编排日期定位和正常收录；`UiaWindowTestReader.read_date_groups()` 只提供轻量日期组快照；`WechatHomeScroller` 继续负责单次滚轮派发。日期定位最大步长来自 `WindowConfig`，普通收录仍使用现有 `scroll_wheel_steps`。

**Tech Stack:** Python 3.13、unittest、Vue 3、TypeScript、YAML 配置。

---

### Task 1: Lock the date-seek behavior with tests

**Files:**
- Modify: `tests/test_window_test_uia_service.py`

- [ ] **Step 1: Write failing tests**

新增测试覆盖：远距离使用 18 步、中距离使用 12 步、近距离使用 6/3 步；日期范围先定位结束日期；检测到 loading 后即使日期签名已变化也要等 loading 消失。

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m unittest tests.test_window_test_uia_service`

Expected: 新增断言失败，因为当前日期定位固定使用普通 3 步，且 loading 出现后会过早退出观察。

### Task 2: Add the configurable date-seek maximum

**Files:**
- Modify: `src/config/app_config.py`
- Modify: `src/config/config_loader.py`
- Modify: `src/config/config_validator.py`
- Modify: `src/config/system.yaml`
- Modify: `data/custom.yaml`

- [ ] **Step 1: Add `date_seek_max_steps`**

在 `WindowConfig` 中增加整数配置，并从 `windows_command.home_scroll.date_seek_max_steps` 加载；校验值不得小于普通滚动步长。

- [ ] **Step 2: Set the tested default**

在系统配置和用户配置中写入 `date_seek_max_steps: 18`，注释明确它只作用于“起始日期”和“日期范围”的日期定位。

### Task 3: Implement adaptive date seeking and loading-cycle waits

**Files:**
- Modify: `src/services/runtime/window_click_flow_diagnostic_service.py`

- [ ] **Step 1: Select a date-seek step**

根据轻量快照中最旧的有效日期与目标日期差值选择 `18/12/6/3`，最大值受 `date_seek_max_steps` 限制；没有有效日期时退回普通步长。

- [ ] **Step 2: Use explicit steps during date location**

日期定位调用 `scroller.scroll(..., direction="down", wheel_steps=selected_steps)`，正常收录继续调用 `scroll_down()`。

- [ ] **Step 3: Locate range end dates before parsing cards**

`range` 模式先定位 `end_date`，`after` 模式先定位 `start_date`；定位完成前只调用 `read_date_groups()`。

- [ ] **Step 4: Complete a loading cycle before continuing**

本轮一旦观察到 `loading=True`，即使签名已经改变也继续轮询，直到 loading 消失且页面已有进展，或者达到 `lazy_load_timeout_seconds`。

- [ ] **Step 5: Run focused tests**

Run: `uv run python -m unittest tests.test_window_test_uia_service tests.test_uia_window_test_reader`

Expected: PASS.

### Task 4: Expose the setting in the configuration page

**Files:**
- Modify: `vue-project/src/pages/SettingsPage.vue`
- Modify: `vue-project/src/__tests__/settingsThreePaneLayout.test.ts`

- [ ] **Step 1: Add the field**

在“主页滚动操作”中增加“日期定位最大步长”，键为 `windows_command.home_scroll.date_seek_max_steps`，单位为“步”，默认值 18。

- [ ] **Step 2: Run the focused frontend test**

Run: `pnpm --dir vue-project test -- settingsThreePaneLayout.test.ts`

Expected: PASS.

### Task 5: Verify and build

**Files:**
- Update generated output: `src/webview/`

- [ ] **Step 1: Run Python checks**

Run: `uv run python -m unittest tests.test_window_test_uia_service tests.test_uia_window_test_reader tests.test_wechat_home_scroller tests.test_config_loader`

Run: `uv run python -m compileall src dev_server.py`

- [ ] **Step 2: Run frontend checks and build**

Run: `pnpm --dir vue-project test`

Run: `pnpm --dir vue-project exec vue-tsc --noEmit`

Run: `pnpm --dir vue-project build`

Expected: tests and type checks pass; Vite refreshes `src/webview`.
