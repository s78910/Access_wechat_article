# Window Diagnostic Scroll Step Input Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在“诊断工具 → 窗口操作 → 滚动页面”按钮左侧增加临时滚动步长输入框，并让单次诊断滚动使用该输入值。

**Architecture:** 前端维护一个不写入 YAML 的诊断步长，通过现有 `/api/diagnostics/window` 请求发送 `scrollSteps`。FastAPI 请求模型限制取值为 1～200，`WindowDiagnosticService`只在`scroll-page`动作中使用该覆盖值，未传时继续读取 YAML 默认值。

**Tech Stack:** Vue 3、TypeScript、VXE UI、FastAPI、Pydantic、Python unittest/Node test。

---

### Task 1: 后端诊断步长覆盖

**Files:**
- Modify: `dev_server.py`
- Modify: `src/services/runtime/window_diagnostic_service.py`
- Create: `tests/test_window_diagnostic_scroll_steps.py`

- [x] **Step 1: 编写失败测试**

测试`WindowDiagnosticPayload`接受 1～200，拒绝范围外值；测试`WindowDiagnosticService.run("scroll-page", scroll_steps=73)`把`73`传给滚动发送器，并在结果中返回实际步长。

- [x] **Step 2: 运行测试确认失败**

Run: `uv run python -m unittest tests.test_window_diagnostic_scroll_steps`

Expected: 因`scrollSteps`字段、`run(..., scroll_steps=...)`尚不存在而失败。

- [x] **Step 3: 实现最小后端改动**

```python
class WindowDiagnosticPayload(BaseModel):
    action: str
    scrollSteps: int | None = Field(default=None, ge=1, le=200)

def run(self, action: str, *, scroll_steps: int | None = None) -> dict[str, Any]:
    if normalized_action == "scroll-page":
        return self._scroll_page(wheel_steps=scroll_steps)
```

接口层将`payload.scrollSteps`传给`WindowDiagnosticService`；自定义测试 runner 继续保持原两参数调用，避免破坏现有测试注入。

- [x] **Step 4: 运行后端测试确认通过**

Run: `uv run python -m unittest tests.test_window_diagnostic_scroll_steps`

Expected: PASS。

### Task 2: 前端输入框与接口绑定

**Files:**
- Modify: `vue-project/src/pages/SettingsPage.vue`
- Modify: `vue-project/src/bridge/pythonApi.ts`
- Modify: `vue-project/src/__tests__/settingsThreePaneLayout.test.ts`

- [x] **Step 1: 编写失败测试**

静态组件测试要求滚动页面动作带有专用步长输入标记、输入范围 1～200，并确认调用接口时发送`scrollSteps`。

- [x] **Step 2: 运行前端测试确认失败**

Run: `node --test vue-project/src/__tests__/settingsThreePaneLayout.test.ts`

Expected: 因输入框和请求参数尚不存在而失败。

- [x] **Step 3: 实现最小前端改动**

```ts
export type WindowDiagnosticOptions = { scrollSteps?: number }

export async function runWindowDiagnosticAction(
  action: WindowDiagnosticAction,
  options: WindowDiagnosticOptions = {},
) {
  return postJson<WindowDiagnosticResult>('/api/diagnostics/window', { action, ...options })
}
```

`SettingsPage.vue`增加诊断专用`windowDiagnosticScrollSteps`，默认同步 YAML 当前值，但后续编辑不写回配置；仅`scroll-page`请求携带该值。

- [x] **Step 4: 运行前端测试确认通过**

Run: `node --test vue-project/src/__tests__/settingsThreePaneLayout.test.ts`

Expected: PASS。

### Task 3: 集成检查

**Files:**
- Verify: `dev_server.py`
- Verify: `src/services/runtime/window_diagnostic_service.py`
- Verify: `vue-project/src/pages/SettingsPage.vue`
- Verify: `vue-project/src/bridge/pythonApi.ts`

- [x] **Step 1: 运行 Python 编译与相关测试**

Run: `uv run python -m compileall -q dev_server.py src/services/runtime/window_diagnostic_service.py tests/test_window_diagnostic_scroll_steps.py`

Run: `uv run python -m unittest tests.test_window_diagnostic_scroll_steps`

- [x] **Step 2: 运行前端类型检查**

Run: `pnpm --dir vue-project type-check`

- [x] **Step 3: 检查差异范围**

Run: `git diff -- dev_server.py src/services/runtime/window_diagnostic_service.py tests/test_window_diagnostic_scroll_steps.py vue-project/src/pages/SettingsPage.vue vue-project/src/bridge/pythonApi.ts vue-project/src/__tests__/settingsThreePaneLayout.test.ts`

确认输入只作用于滚动页面诊断，不修改 YAML、不影响回弹滚动、窗口测试和主流程。
