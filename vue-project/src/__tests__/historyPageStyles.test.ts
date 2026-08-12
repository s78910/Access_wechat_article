import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const currentDir = dirname(fileURLToPath(import.meta.url))
const historyPageVue = readFileSync(resolve(currentDir, '../pages/HistoryPage.vue'), 'utf8')

function extractRule(source: string, selector: string) {
  const normalizedSource = source.replace(/\r\n/g, '\n')
  const escaped = selector.replace(/[.*+?^$()|[\]\\]/g, '\\$&')
  const match = normalizedSource.match(new RegExp(escaped + '\\s*\\{[\\s\\S]*?\\n\\}'))

  assert.ok(match, selector + ' rule should exist')

  return match[0]
}

test('采集历史筛选控件和按钮使用轻量纸质样式', () => {
  const controlRule = extractRule(
    historyPageVue,
    '.history-list :deep(.history-vxe-control.vxe-input),\n.history-list :deep(.history-vxe-control.vxe-select),\n.history-list :deep(.history-vxe-control.vxe-date-range-picker)',
  )
  const innerRule = extractRule(
    historyPageVue,
    '.history-list :deep(.history-vxe-control .vxe-input--inner),\n.history-list :deep(.history-vxe-control .vxe-date-range-picker--inner),\n.history-list :deep(.history-vxe-control .vxe-date-range-picker--prefix),\n.history-list :deep(.history-vxe-control .vxe-date-range-picker--suffix)',
  )
  const buttonRule = extractRule(historyPageVue, '.history-vxe-button')
  const primaryButtonRule = extractRule(historyPageVue, '.history-vxe-button.primary')
  const ghostButtonRule = extractRule(historyPageVue, '.history-vxe-button.ghost')

  assert.match(controlRule, /font-weight:\s*400;/)
  assert.match(innerRule, /font-weight:\s*400;/)
  assert.match(buttonRule, /box-shadow:\s*var\(--paper-shadow-sm\);/)
  assert.match(buttonRule, /font-weight:\s*500;/)
  assert.match(primaryButtonRule, /background:\s*#2d75d6;/)
  assert.match(ghostButtonRule, /background:\s*rgba\(255, 255, 255, 0\.5\);/)
  assert.doesNotMatch(buttonRule + primaryButtonRule + ghostButtonRule, /radial-gradient|linear-gradient|backdrop-filter/)
})

test('采集历史筛选区移动到标题右侧并删除查询按钮', () => {
  const headerBlock = historyPageVue.match(/<div class="history-list-header">[\s\S]*?<\/div>\s*<\/div>/)
  const filterBlock = historyPageVue.match(/<div class="filters-row history-filters">[\s\S]*?<\/div>/)
  const historyListHeaderRule = extractRule(historyPageVue, '.history-list-header')
  const historyFiltersRule = extractRule(historyPageVue, '.history-filters')

  assert.ok(headerBlock, 'history list should use a header row that contains title and filters')
  assert.ok(filterBlock, 'history filters should exist')
  assert.match(headerBlock[0], /<h2 class="section-heading">/)
  assert.match(headerBlock[0], /<div class="filters-row history-filters">/)
  assert.match(filterBlock[0], /placeholder="搜索记录"/)
  assert.doesNotMatch(filterBlock[0], /handleHistorySearch|fa-magnifying-glass|查询/)
  assert.doesNotMatch(historyPageVue, /async function handleHistorySearch/)
  assert.match(
    historyPageVue,
    /watch\(keyword, \(\) => \{[\s\S]*?scheduleHistoryRecordsLoad\(\)/,
  )
  assert.match(
    historyPageVue,
    /watch\(\[selectedCollectType, selectedStatus, selectedCollectStartDate, selectedCollectEndDate\], async \(\) => \{[\s\S]*?await loadHistoryRecords\(1, historyPageSize\.value\)/,
  )

  assert.match(historyListHeaderRule, /grid-template-columns:\s*max-content minmax\(0, 1fr\);/)
  assert.match(historyListHeaderRule, /min-height:\s*48px;/)
  assert.match(historyFiltersRule, /justify-self:\s*end;/)
  assert.match(historyFiltersRule, /width:\s*min\(100%, 660px\);/)
  assert.match(historyFiltersRule, /gap:\s*10px;/)
  assert.match(historyFiltersRule, /margin-top:\s*0;/)
  assert.match(historyFiltersRule, /background:\s*transparent;/)
  assert.match(historyFiltersRule, /box-shadow:\s*none;/)
})

test('采集历史日期筛选使用数据档案页同款日期范围组件', () => {
  const dateRangeBlock = historyPageVue.match(/<VxeDateRangePicker[\s\S]*?\/?>/)
  const historyFiltersRule = extractRule(historyPageVue, '.history-filters')
  const dateRangeControlRule = extractRule(
    historyPageVue,
    '.history-list :deep(.history-date-range-picker.vxe-date-range-picker)',
  )
  const dateRangeInnerRule = extractRule(
    historyPageVue,
    '.history-list :deep(.history-date-range-picker .vxe-date-range-picker--inner)',
  )

  assert.ok(dateRangeBlock, 'history filters should use VxeDateRangePicker')
  assert.match(dateRangeBlock[0], /v-model:start-value="selectedCollectStartDate"/)
  assert.match(dateRangeBlock[0], /v-model:end-value="selectedCollectEndDate"/)
  assert.match(dateRangeBlock[0], /separator=" ~ "/)
  assert.match(dateRangeBlock[0], /placeholder="采集起始 ~ 结束日期"/)
  assert.match(dateRangeBlock[0], /class="history-vxe-control history-date-range-picker"/)
  assert.doesNotMatch(historyPageVue, /<VxeDatePicker/)

  assert.match(
    historyFiltersRule,
    /grid-template-columns:\s*minmax\(136px, 156px\) minmax\(92px, 104px\) minmax\(92px, 104px\) minmax\(188px, 1fr\) 76px;/,
  )
  assert.match(dateRangeControlRule, /height:\s*38px;/)
  assert.match(dateRangeInnerRule, /text-align:\s*center;/)
})

test('采集历史关键词搜索框为下拉箭头保留右侧缓冲', () => {
  const keywordRule = extractRule(historyPageVue, '.history-keyword')
  const dateRangeRule = extractRule(historyPageVue, '.history-date-range-picker')
  const keywordSuffixRule = extractRule(
    historyPageVue,
    '.history-list :deep(.history-keyword .vxe-input--suffix)',
  )
  const keywordInnerRule = extractRule(
    historyPageVue,
    '.history-list :deep(.history-keyword .vxe-input--inner)',
  )

  assert.match(keywordRule, /min-width:\s*0;/)
  assert.match(dateRangeRule, /min-width:\s*0;/)
  assert.match(keywordSuffixRule, /width:\s*28px;/)
  assert.match(keywordSuffixRule, /flex-basis:\s*28px;/)
  assert.match(keywordSuffixRule, /padding-right:\s*6px;/)
  assert.match(keywordSuffixRule, /box-sizing:\s*border-box;/)
  assert.match(keywordInnerRule, /padding-right:\s*8px;/)
})

test('采集历史表格区域沿用主页面纸质卡片层次', () => {
  const historyListRule = extractRule(historyPageVue, '.history-list')
  const tableWrapRule = extractRule(historyPageVue, '.history-vxe-table-wrap')
  const baseGridRule = extractRule(historyPageVue, '.history-vxe-grid')
  const gridRule = extractRule(historyPageVue, '.history-list :deep(.history-vxe-grid.vxe-grid)')
  const headerRule = extractRule(historyPageVue, '.history-list :deep(.history-vxe-grid .vxe-header--column)')
  const bodyRule = extractRule(historyPageVue, '.history-list :deep(.history-vxe-grid .vxe-body--column)')
  const cellRule = extractRule(historyPageVue, '.history-list :deep(.history-vxe-grid .vxe-cell)')
  const paginationRule = extractRule(historyPageVue, '.history-vxe-pagination')

  assert.match(historyPageVue, /const HISTORY_VISIBLE_ROWS = 15/)
  assert.match(historyPageVue, /const historyPageSize = ref\(HISTORY_VISIBLE_ROWS\)/)
  assert.match(historyPageVue, /const historyTableWrapRef = ref<HTMLElement \| null>\(null\)/)
  assert.match(historyPageVue, /function updateHistoryTableMetrics\(\)/)
  assert.match(historyPageVue, /Math\.floor\(\(historyTableBodyHeight\.value \/ HISTORY_VISIBLE_ROWS\) \* 100\) \/ 100/)
  assert.match(historyPageVue, /historyTableBodyHeight\.value \/ HISTORY_VISIBLE_ROWS/)
  assert.match(historyPageVue, /new ResizeObserver\(updateHistoryTableMetrics\)/)
  assert.match(historyPageVue, /ref="historyTableWrapRef"/)
  assert.match(historyListRule, /display:\s*flex;/)
  assert.match(historyListRule, /flex-direction:\s*column;/)
  assert.match(tableWrapRule, /--history-body-height:\s*480px;/)
  assert.match(tableWrapRule, /flex:\s*1 1 0;/)
  assert.match(tableWrapRule, /height:\s*auto;/)
  assert.match(tableWrapRule, /margin-top:\s*6px;/)
  assert.match(baseGridRule, /--vxe-ui-table-row-height-mini:\s*var\(--history-row-height, 32px\);/)
  assert.match(paginationRule, /flex:\s*0 0 auto;/)
  assert.match(paginationRule, /margin-top:\s*6px;/)
  assert.match(tableWrapRule, /border:\s*1px solid rgba\(104, 141, 181, 0\.18\);/)
  assert.match(tableWrapRule, /background:\s*rgba\(255, 255, 255, 0\.38\);/)
  assert.match(tableWrapRule, /box-shadow:\s*inset 0 1px 0 rgba\(255, 255, 255, 0\.58\);/)
  assert.match(gridRule, /font-weight:\s*400;/)
  assert.match(headerRule, /background:\s*rgba\(234, 244, 251, 0\.48\);/)
  assert.match(headerRule, /font-weight:\s*500;/)
  assert.match(bodyRule, /height:\s*var\(--history-row-height, 32px\) !important;/)
  assert.match(bodyRule, /font-weight:\s*400;/)
  assert.match(cellRule, /min-height:\s*var\(--history-row-height, 32px\);/)
  assert.match(cellRule, /height:\s*var\(--history-row-height, 32px\);/)
})

test('采集历史详情和统计区域降低字重并弱化绿色占比', () => {
  const detailStrongRule = extractRule(historyPageVue, '.task-detail .detail-row strong')
  const recordContentRule = extractRule(historyPageVue, '.record-content span')
  const emptyStrongRule = extractRule(historyPageVue, '.detail-empty strong')
  const emptySpanRule = extractRule(historyPageVue, '.detail-empty span')
  const captionRule = extractRule(historyPageVue, '.chart-caption')
  const trendBarRule = extractRule(historyPageVue, '.trend-bar')
  const trendLabelRule = extractRule(historyPageVue, '.trend-item small')
  const summaryCardRule = extractRule(historyPageVue, '.summary-grid div')
  const summaryStrongRule = extractRule(historyPageVue, '.summary-grid strong')
  const summarySpanRule = extractRule(historyPageVue, '.summary-grid span')

  assert.match(detailStrongRule, /font-weight:\s*500;/)
  assert.match(recordContentRule, /font-weight:\s*400;/)
  assert.match(emptyStrongRule, /font-weight:\s*500;/)
  assert.match(emptySpanRule, /font-weight:\s*400;/)
  assert.match(captionRule, /font-weight:\s*500;/)
  assert.match(trendBarRule, /linear-gradient\(180deg, #79aee8, #2d75d6\)/)
  assert.doesNotMatch(trendBarRule, /#27956f|#67b89d/)
  assert.match(trendLabelRule, /font-weight:\s*500;/)
  assert.match(summaryCardRule, /box-shadow:\s*var\(--paper-shadow-sm\);/)
  assert.match(summaryStrongRule, /font-weight:\s*500;/)
  assert.match(summarySpanRule, /font-weight:\s*400;/)
})

test('采集历史暗色模式保持低刺激纸质层次', () => {
  const darkTableWrapRule = extractRule(historyPageVue, ':global(.collector-app.dark) .history-vxe-table-wrap')
  const darkPrimaryButtonRule = extractRule(
    historyPageVue,
    ':global(.collector-app.dark) .history-vxe-button.primary',
  )
  const darkEmptyRule = extractRule(historyPageVue, ':global(.collector-app.dark) .detail-empty')

  assert.match(darkTableWrapRule, /background:\s*rgba\(15, 24, 39, 0\.52\);/)
  assert.match(darkPrimaryButtonRule, /background:\s*#2f6fb5;/)
  assert.match(darkEmptyRule, /background:\s*rgba\(15, 24, 39, 0\.36\);/)
  assert.doesNotMatch(darkPrimaryButtonRule, /linear-gradient|radial-gradient|backdrop-filter/)
})
