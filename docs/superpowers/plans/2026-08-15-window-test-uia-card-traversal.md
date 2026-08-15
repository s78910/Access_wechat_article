# Window Test UIA Card Traversal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用独立 UIA 日期组/文章卡片快照替换窗口测试现有的 HomeArticleCursor 诊断流程。

**Architecture:** 新增只读 UIA 快照模块，按日期组直接子卡片构建稳定有序数据；诊断服务持有上一屏末尾标记，负责激活、滚动后轮询、回弹和日期/数量过滤。现有 FastAPI 异步任务与 Vue 弹窗继续复用，只调整说明和文章字段。

**Tech Stack:** Python 3.13、uiautomation、FastAPI、Vue 3、TypeScript、unittest、Node test runner。

---

### Task 1: UIA 日期组和文章卡片快照

**Files:**
- Create: `src/modules/window/uia_window_test_reader.py`
- Create: `tests/test_uia_window_test_reader.py`

- [ ] 写失败测试：没有“阅读 xx”的日期组直接子卡片仍被识别，完整标题来自叶子 `TextControl.Name`。
- [ ] 写失败测试：部分可见高度至少 10 像素时保留并计算裁剪矩形中心，小于 10 像素时忽略。
- [ ] 运行 `uv run python -m unittest tests.test_uia_window_test_reader`，确认模块缺失导致失败。
- [ ] 实现一次性 UIA 树快照、日期组解析、卡片排序、可视裁剪和稳定标记。
- [ ] 再次运行测试，确认所有快照规则通过。

### Task 2: 独立窗口测试编排

**Files:**
- Modify: `src/services/capture/window_runtime_factory.py`
- Replace: `src/services/runtime/window_click_flow_diagnostic_service.py`
- Create: `tests/test_window_test_uia_service.py`

- [ ] 写失败测试：服务启动时激活主页，首次快照按顺序记录文章，不创建旧游标。
- [ ] 写失败测试：滚动后通过上一条“日期+标题”只追加后续可见卡片。
- [ ] 写失败测试：无新卡片达到配置时间后执行回弹，回弹后重新读取。
- [ ] 运行服务测试并确认新工厂接口和新编排尚不存在。
- [ ] 为运行时工厂增加独立快照读取器和滚动器创建方法，替换服务旧游标逻辑。
- [ ] 运行服务测试，确认停止、日期边界、无候选和异常返回保留已有记录。

### Task 3: 弹窗字段与前端说明

**Files:**
- Modify: `src/services/runtime/window_click_flow_diagnostic_service.py`
- Modify: `vue-project/src/pages/SettingsPage.vue`
- Modify: `vue-project/src/__tests__/windowClickFlowDateFilter.test.ts`

- [ ] 写失败测试：文章条目展示完整卡片坐标、可视坐标、可视高度和中心点，不再展示阅读坐标。
- [ ] 写失败测试：功能说明明确首次激活主页、UIA 卡片遍历、滚动后重新读取且不点击文章。
- [ ] 实现新的后端条目字段和前端说明，保留现有日期控件、实时轮询和立即停止。
- [ ] 运行前端相关测试，确认按钮绑定和筛选参数保持不变。

### Task 4: 回归检查

**Files:**
- Verify only: all files above

- [ ] 运行新增 Python 测试和现有窗口日期、滚动、API 相关测试。
- [ ] 运行前端窗口测试相关测试和 TypeScript 类型检查。
- [ ] 运行 Python 编译检查与 `git diff --check`；不启动或重启前后端。
