import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const appVue = readFileSync(fileURLToPath(new URL('../App.vue', import.meta.url)), 'utf8')

test('指定记录总量卡片保留标题并以下拉菜单提供四种日期筛选方式', () => {
  assert.match(appVue, /type TaskDateFilterMode = 'all' \| 'range' \| 'before' \| 'after'/)
  assert.match(appVue, /const taskDateFilterMode = ref<TaskDateFilterMode>\('all'\)/)
  assert.match(appVue, /\{ label: '不限日期', value: 'all' \}/)
  assert.match(appVue, /\{ label: '日期范围', value: 'range' \}/)
  assert.match(appVue, /\{ label: '截止日期', value: 'before' \}/)
  assert.match(appVue, /\{ label: '起始日期', value: 'after' \}/)

  const card = appVue.match(
    /<article class="task-card task-card-volume panel">[\s\S]*?<\/article>/,
  )
  assert.ok(card, '缺少指定记录总量的独立卡片布局')
  assert.match(card[0], /<h2>指定记录总量<\/h2>/)
  assert.match(card[0], /<ADropdown/)
  assert.match(card[0], /:trigger="\['click'\]"/)
  assert.match(card[0], /class="task-date-filter-trigger"/)
  assert.match(card[0], /\{\{ taskDateFilterLabel \}\}/)
  assert.match(card[0], /<AMenu :selected-keys="\[taskDateFilterMode\]">/)
  assert.match(card[0], /<AMenuItem[\s\S]*?v-for="option in taskDateFilterOptions"/)
  assert.match(card[0], /@click="selectTaskDateFilterMode\(option\.value\)"/)
  assert.doesNotMatch(card[0], /<VxeSelect/)
  assert.doesNotMatch(appVue, /taskDatePopupConfig/)
  assert.doesNotMatch(card[0], /role="radiogroup"/)
  assert.doesNotMatch(card[0], /type="radio"/)
  assert.doesNotMatch(card[0], /默认为 1，设为 0 时遍历全部内容/)
})

test('日期控件使用 Ant Design DatePicker 系列并按筛选模式切换', () => {
  assert.match(appVue, /const taskStartDate = ref\(''\)/)
  assert.match(appVue, /const taskEndDate = ref\(''\)/)
  assert.match(appVue, /const taskDateRangeValue = computed<TaskDateRangeValue>/)
  assert.match(appVue, /class="[^"]*task-date-row[^"]*"/)
  assert.match(appVue, /<ARangePicker[\s\S]*?v-model:value="taskDateRangeValue"/)
  assert.match(appVue, /<ADatePicker[\s\S]*?v-model:value="taskEndDate"/)
  assert.match(appVue, /<ADatePicker[\s\S]*?v-model:value="taskStartDate"/)
  assert.match(appVue, /value-format="YYYY-MM-DD"/)
  assert.match(appVue, /taskDateFilterMode === 'all'[\s\S]*?:disabled="true"/)
  assert.doesNotMatch(appVue, /<VxeDate(?:Range)?Picker/)
  assert.match(
    appVue,
    /\.task-volume-body\s*\{[\s\S]*?grid-template-rows:\s*auto auto auto auto;/,
  )
})

test('任务数量沿用步进器并提供零值说明浮层', () => {
  const card = appVue.match(
    /<article class="task-card task-card-volume panel">[\s\S]*?<\/article>/,
  )
  assert.ok(card)
  assert.match(card[0], /class="number-stepper"/)
  assert.match(card[0], /class="task-count-hint"/)
  assert.match(card[0], /设为0时遍历日期范围内全部内容/)
  assert.match(card[0], /showDescriptionTooltip/)
})

test('日期筛选暂不写入主流程后端参数', () => {
  const builder = appVue.match(/function buildTaskRunOptions\(\): TaskRunOptions \{[\s\S]*?\n\}/)
  assert.ok(builder)
  assert.doesNotMatch(builder[0], /taskDateFilterMode|taskStartDate|taskEndDate/)
})

test('新增设置标签与获取内容选项使用相同字号', () => {
  const taskLabelRule = appVue.match(/\.task-control-label\s*\{(?<body>[\s\S]*?)\}/)
  const downloadOptionRule = appVue.match(/\.download-option\s*\{(?<body>[\s\S]*?)\}/)
  const dateInputRule = appVue.match(
    /\.task-date-control :deep\(\.ant-picker-input > input\)\s*\{(?<body>[\s\S]*?)\}/,
  )

  assert.ok(taskLabelRule?.groups?.body)
  assert.ok(downloadOptionRule?.groups?.body)
  assert.ok(dateInputRule?.groups?.body)
  assert.match(taskLabelRule.groups.body, /font-size:\s*14px;/)
  assert.match(downloadOptionRule.groups.body, /font-size:\s*14px;/)
  assert.match(dateInputRule.groups.body, /font-size:\s*14px;/)
})

test('日期控件底行与获取内容多选框保持一致的底部留白', () => {
  const dateRowRule = appVue.match(/\.task-date-row\s*\{(?<body>[\s\S]*?)\}/)

  assert.ok(dateRowRule?.groups?.body)
  assert.match(dateRowRule.groups.body, /position:\s*relative;/)
  assert.match(dateRowRule.groups.body, /grid-template-columns:\s*minmax\(0,\s*1fr\);/)
  assert.match(dateRowRule.groups.body, /width:\s*100%;/)
  assert.match(dateRowRule.groups.body, /transform:\s*translateY\(4px\);/)
})

test('日期操作行恢复简短标签并复用文章详情选项样式', () => {
  assert.match(appVue, /all: '日期范围'/)
  assert.match(appVue, /range: '日期范围'/)
  assert.match(appVue, /before: '截止日期'/)
  assert.match(appVue, /after: '起始日期'/)
  assert.match(
    appVue,
    /class="task-control-label task-date-label download-option selected locked"/,
  )

  const dateLabelRule = appVue.match(
    /\.task-date-label\s*\{(?<body>[\s\S]*?)\}/,
  )
  assert.ok(dateLabelRule?.groups?.body)
  assert.match(dateLabelRule.groups.body, /width:\s*120px;/)
  assert.match(dateLabelRule.groups.body, /height:\s*34px;/)
  assert.match(dateLabelRule.groups.body, /min-height:\s*34px;/)
  assert.match(dateLabelRule.groups.body, /cursor:\s*default;/)
  assert.match(dateLabelRule.groups.body, /pointer-events:\s*none;/)

  const dateLabelPositionRule = appVue.match(
    /\.task-date-row > \.task-control-label\s*\{(?<body>[\s\S]*?)\}/,
  )
  assert.ok(dateLabelPositionRule?.groups?.body)
  assert.match(dateLabelPositionRule.groups.body, /right:\s*calc\(100% \+ 12px\);/)
})

test('日期范围的两个输入区等宽且使用官方箭头居中分隔', () => {
  const rangeInputRule = appVue.match(
    /\.task-date-control :deep\(\.ant-picker-range \.ant-picker-input\)\s*\{(?<body>[\s\S]*?)\}/,
  )
  const rangeSeparatorRule = appVue.match(
    /\.task-date-control :deep\(\.ant-picker-range-separator\)\s*\{(?<body>[\s\S]*?)\}/,
  )

  assert.ok(rangeInputRule?.groups?.body)
  assert.match(rangeInputRule.groups.body, /flex:\s*1 1 0;/)
  assert.match(rangeInputRule.groups.body, /min-width:\s*0;/)
  assert.ok(rangeSeparatorRule?.groups?.body)
  assert.match(rangeSeparatorRule.groups.body, /display:\s*grid;/)
  assert.match(rangeSeparatorRule.groups.body, /place-items:\s*center;/)
  assert.match(rangeSeparatorRule.groups.body, /flex:\s*0 0 28px;/)
  assert.match(rangeSeparatorRule.groups.body, /padding:\s*0;/)
  assert.doesNotMatch(appVue, /#separator/)
  assert.doesNotMatch(appVue, /task-date-separator/)
})

test('单日期选择后显示中文星期但仍保存标准日期字符串', () => {
  assert.match(
    appVue,
    /taskDateFilterMode === 'before'[\s\S]*?format="YYYY-MM-DD {2}dddd"[\s\S]*?value-format="YYYY-MM-DD"/,
  )
  assert.match(
    appVue,
    /taskDateFilterMode === 'after'[\s\S]*?format="YYYY-MM-DD {2}dddd"[\s\S]*?value-format="YYYY-MM-DD"/,
  )
  assert.match(
    appVue,
    /<ARangePicker[\s\S]*?format="YYYY-MM-DD"[\s\S]*?value-format="YYYY-MM-DD"/,
  )
})
