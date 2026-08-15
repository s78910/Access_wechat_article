# Window Test Date Priority Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让窗口测试以 UIA 日期组优先控制日期范围，并在起始日期定位期间不处理文章卡片。

**Architecture:** `uia_window_test_reader.py`增加轻量日期组快照；`window_click_flow_diagnostic_service.py`增加起始日期定位阶段，并保留现有完整卡片遍历；前后端统一用`maxRecords=0`表示日期范围和截止日期模式不限数量。

**Tech Stack:** Python 3.13、uiautomation、FastAPI/Pydantic、Vue 3、TypeScript、Node test runner。

---

### Task 1: 锁定日期规则

**Files:**
- Modify: `tests/test_window_article_date_filter.py`
- Modify: `tests/test_window_test_uia_service.py`
- Modify: `tests/test_uia_window_test_reader.py`
- Modify: `vue-project/src/__tests__/windowClickFlowDateFilter.test.ts`

- [ ] 增加截止日期从当前位置记录到边界、起始日期先定位后记录、范围/截止数量为零的测试。
- [ ] 运行相关测试，确认测试因旧语义失败。

### Task 2: 增加轻量日期组快照

**Files:**
- Modify: `src/modules/window/uia_window_test_reader.py`

- [ ] 增加只解析日期行、日期组区域和可视区域的快照对象。
- [ ] 复用同一次 UIA 树快照基础逻辑，确保轻量接口不调用文章卡片解析。
- [ ] 运行 UIA reader 测试并确认通过。

### Task 3: 调整后端日期编排

**Files:**
- Modify: `src/modules/window/article_date_filter.py`
- Modify: `src/services/runtime/window_click_flow_diagnostic_service.py`
- Modify: `dev_server.py`

- [ ] 将截止日期定义为从当前位置记录到截止日期，将起始日期定义为定位后向更早方向记录。
- [ ] 为起始日期增加只读取日期组的定位、等待和回弹阶段。
- [ ] 允许`maxRecords=0`作为不限数量，并让日期边界成为停止条件。
- [ ] 运行后端相关测试并确认通过。

### Task 4: 调整前端联动

**Files:**
- Modify: `vue-project/src/pages/SettingsPage.vue`

- [ ] 日期范围或截止日期模式将任务数量固定为`0`并禁用数量输入。
- [ ] 不限日期或起始日期模式恢复`20`，允许在`1-20`之间调整。
- [ ] 运行前端相关测试和 TypeScript 检查。

### Task 5: 回归检查

**Files:**
- Test only

- [ ] 运行窗口测试、日期筛选、UIA reader相关 Python 测试。
- [ ] 运行窗口筛选相关前端测试。
- [ ] 运行 Python 编译检查和 Vue TypeScript检查。

