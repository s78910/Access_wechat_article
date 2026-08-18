import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const settingsPageSource = readFileSync(
  fileURLToPath(new URL('../pages/SettingsPage.vue', import.meta.url)),
  'utf8',
)
const pythonApiSource = readFileSync(
  fileURLToPath(new URL('../bridge/pythonApi.ts', import.meta.url)),
  'utf8',
)

test('窗口点击流程提供任务数量和四种主页日期筛选方式', () => {
  assert.match(settingsPageSource, /windowClickFlowMaxRecords/)
  assert.match(settingsPageSource, /不限日期/)
  assert.match(settingsPageSource, /日期范围/)
  assert.match(settingsPageSource, /截止日期/)
  assert.match(settingsPageSource, /起始日期/)
  assert.match(settingsPageSource, /windowClickFlowStartDate/)
  assert.match(settingsPageSource, /windowClickFlowEndDate/)
})

test('窗口点击流程使用 Ant Design Vue 日期选择组件', () => {
  const dateRangeBlock = settingsPageSource.match(/<ARangePicker[\s\S]*?\/>/)
  const datePickerBlocks = settingsPageSource.match(/<ADatePicker[\s\S]*?\/>/g) ?? []

  assert.ok(dateRangeBlock)
  assert.match(dateRangeBlock[0], /v-model:value="windowClickFlowDateRangeValue"/)
  assert.match(dateRangeBlock[0], /separator=" ~ "/)
  assert.match(dateRangeBlock[0], /value-format="YYYY-MM-DD"/)
  assert.match(dateRangeBlock[0], /popup-class-name="window-click-flow-date-range-picker-panel"/)
  assert.match(dateRangeBlock[0], /class="settings-ant-control window-click-flow-date-range-picker"/)

  assert.equal(datePickerBlocks.length, 2)
  for (const block of datePickerBlocks) {
    assert.match(block, /value-format="YYYY-MM-DD"/)
    assert.match(block, /format="YYYY-MM-DD"/)
    assert.match(block, /popup-class-name="window-click-flow-date-picker-panel"/)
    assert.match(block, /class="settings-ant-control window-click-flow-date-picker"/)
  }
  assert.doesNotMatch(settingsPageSource, /<input\b[^>]*\btype="date"[^>]*>/)
})

test('窗口点击流程控件在同一行保留完整的日期范围显示', () => {
  assert.match(settingsPageSource, /\.window-click-flow-fields \{[\s\S]*?flex-wrap:\s*nowrap;/)
  assert.match(settingsPageSource, /\.window-click-flow-fields \{[\s\S]*?gap:\s*6px;/)
  assert.match(settingsPageSource, /\.window-click-flow-field--mode \{[\s\S]*?flex:\s*0 0 116px;/)
  assert.match(settingsPageSource, /\.window-click-flow-field--range \{[\s\S]*?flex:\s*0 0 248px;/)
  assert.match(settingsPageSource, /\.window-click-flow-description-line > \.settings-ant-button \{[\s\S]*?flex:\s*0 0 168px;/)
})

test('窗口点击流程配置依次展示日期筛选、任务数量和日期条件', () => {
  const fieldsStart = settingsPageSource.indexOf('class="window-click-flow-fields"')
  const modeIndex = settingsPageSource.indexOf('window-click-flow-field--mode', fieldsStart)
  const countIndex = settingsPageSource.indexOf('window-click-flow-field--count', fieldsStart)
  const dateIndex = settingsPageSource.indexOf('window-click-flow-field--date', fieldsStart)

  assert.ok(fieldsStart >= 0)
  assert.ok(modeIndex > fieldsStart)
  assert.ok(countIndex > modeIndex)
  assert.ok(dateIndex > countIndex)
})

test('窗口点击流程将标题、说明按钮和筛选控件分成三行', () => {
  assert.match(settingsPageSource, /v-if="action\.showWindowClickFlowOptions"\s+class="window-click-flow-layout"/)
  assert.match(settingsPageSource, /class="window-click-flow-title"/)
  assert.match(settingsPageSource, /class="window-click-flow-description-line"/)
  assert.match(settingsPageSource, /class="window-click-flow-description-line"[\s\S]*?action\.description[\s\S]*?action\.buttonLabel/)
  assert.match(settingsPageSource, /class="window-click-flow-fields"/)
  assert.match(settingsPageSource, /\.window-click-flow-layout \{[\s\S]*?grid-template-rows:\s*auto auto auto;/)
  assert.match(settingsPageSource, /\.window-click-flow-fields \{[\s\S]*?grid-row:\s*2;/)
  assert.match(settingsPageSource, /\.window-click-flow-description-line \{[\s\S]*?grid-row:\s*3;[\s\S]*?justify-content:\s*space-between;/)
})

test('窗口测试将任务数量和日期条件发送给后端', () => {
  assert.match(pythonApiSource, /export type WindowClickFlowDiagnosticOptions/)
  assert.match(pythonApiSource, /maxRecords: number/)
  assert.match(pythonApiSource, /dateFilterMode:/)
  assert.match(pythonApiSource, /startDate\?: string/)
  assert.match(pythonApiSource, /endDate\?: string/)
  assert.match(settingsPageSource, /startWindowClickFlowDiagnostic\(options\)/)
})

test('日期范围和截止日期将任务数量固定为零', () => {
  assert.match(settingsPageSource, /const windowClickFlowUsesUnlimitedRecords = computed/)
  assert.match(
    settingsPageSource,
    /windowClickFlowMaxRecords\.value = windowClickFlowUsesUnlimitedRecords\.value \? 0 : 20/,
  )
  assert.match(
    settingsPageSource,
    /:disabled="isWindowClickFlowDiagnosticRunning \|\| windowClickFlowUsesUnlimitedRecords"/,
  )
  assert.match(
    settingsPageSource,
    /const maxRecords = windowClickFlowUsesUnlimitedRecords\.value/,
  )
})

test('窗口测试首次激活主页并按 UIA 日期组卡片遍历', () => {
  assert.match(settingsPageSource, /首次立即激活公众号主页/)
  assert.match(settingsPageSource, /UIA 日期组和文章卡片/)
  assert.match(settingsPageSource, /滚动后重新读取/)
  assert.match(settingsPageSource, /不点击文章/)
  assert.match(settingsPageSource, /主页内容读取结果/)
  assert.match(pythonApiSource, /recognizedCount\?: number/)
  assert.match(pythonApiSource, /skippedCount\?: number/)
  assert.doesNotMatch(pythonApiSource, /clickedCount\?: number/)
  assert.doesNotMatch(pythonApiSource, /openedCount\?: number/)
  assert.doesNotMatch(pythonApiSource, /closedCount\?: number/)
})

test('窗口测试弹窗只展示成功识别的文章记录', () => {
  assert.match(
    pythonApiSource,
    /kind\?: 'summary' \| 'operation' \| 'discarded' \| 'article'/,
  )
  assert.match(settingsPageSource, /function applyWindowClickFlowDiagnosticResult/)
  assert.match(settingsPageSource, /filter\(\(item\) => item\.kind === 'article'\)/)
  assert.match(settingsPageSource, /applyWindowClickFlowDiagnosticResult\(started\)/)
  assert.match(settingsPageSource, /applyWindowClickFlowDiagnosticResult\(latest\)/)
  assert.match(
    settingsPageSource,
    /message: '正在启动主页内容读取测试\.\.\.'[\s\S]*?items: \[\]/,
  )
})

test('窗口测试结果类型保留后端诊断文件路径', () => {
  assert.match(pythonApiSource, /traceDir\?: string/)
  assert.match(pythonApiSource, /executionLogPath\?: string/)
  assert.match(pythonApiSource, /resultPath\?: string/)
})

test('诊断时间线只在用户停留底部时自动跟随最新记录', () => {
  assert.match(settingsPageSource, /ref="diagnosticResultListRef"/)
  assert.match(settingsPageSource, /@scroll="handleDiagnosticResultListScroll"/)
  assert.match(settingsPageSource, /shouldAutoFollowDiagnosticResult/)
  assert.match(settingsPageSource, /scrollHeight\s*-\s*scrollTop\s*-\s*clientHeight/)
  assert.match(settingsPageSource, /scrollDiagnosticResultListToEnd/)
  assert.match(settingsPageSource, /nextTick/)
})
