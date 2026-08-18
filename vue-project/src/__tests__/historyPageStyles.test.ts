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

test('采集历史筛选区使用 Ant Design Vue 控件', () => {
  const filterBlock = historyPageVue.match(/<div class="filters-row history-filters">[\s\S]*?<\/div>/)
  const filterRule = extractRule(historyPageVue, '.history-filters')
  const controlRule = extractRule(historyPageVue, '.history-ant-control,\n.history-date-picker,\n.history-refresh-button')
  const selectRule = extractRule(historyPageVue, '.history-list :deep(.history-ant-select.ant-select .ant-select-selector)')
  const pickerRule = extractRule(historyPageVue, '.history-list :deep(.history-date-picker.ant-picker)')

  assert.ok(filterBlock, 'history filters should exist')
  assert.ok(
    filterBlock[0].indexOf('class="history-refresh-button"') <
      filterBlock[0].indexOf('class="history-ant-control history-ant-select history-keyword"'),
    'refresh button should be placed before the keyword search control',
  )
  assert.match(filterBlock[0], /<ASelect[\s\S]*?class="history-ant-control history-ant-select history-keyword"/)
  assert.match(filterBlock[0], /<ATreeSelect[\s\S]*?class="history-ant-control history-ant-select history-filter-tree"/)
  assert.match(filterBlock[0], /tree-checkable/)
  assert.match(filterBlock[0], /:tree-data="historyFilterTreeData"/)
  assert.match(filterBlock[0], /aria-label="采集筛选"/)
  assert.doesNotMatch(filterBlock[0], /v-model:value="selectedCollectType"/)
  assert.doesNotMatch(filterBlock[0], /v-model:value="selectedStatus"/)
  assert.match(filterBlock[0], /<ARangePicker[\s\S]*?v-model:value="selectedCollectDateRange"/)
  assert.match(filterBlock[0], /<AButton[\s\S]*?class="history-refresh-button"/)
  assert.doesNotMatch(filterBlock[0], /VxeSelect|VxeDateRangePicker|VxeButton|handleHistorySearch/)
  assert.doesNotMatch(historyPageVue, /historySuggestionRemoteConfig/)

  assert.match(filterRule, /grid-template-columns:\s*76px minmax\(154px, 176px\) minmax\(132px, 152px\) minmax\(250px, 1fr\);/)
  assert.match(filterRule, /width:\s*min\(100%, 696px\);/)
  assert.match(filterRule, /gap:\s*10px;/)
  assert.match(controlRule, /height:\s*38px;/)
  assert.match(selectRule, /height:\s*38px;/)
  assert.match(pickerRule, /height:\s*38px;/)
})

test('采集历史搜索框使用放大镜提示，类型和状态合并为树选择多选框', () => {
  const filterBlock = historyPageVue.match(/<div class="filters-row history-filters">[\s\S]*?<\/div>/)
  const treeSelect = filterBlock?.[0].match(
    /<ATreeSelect[\s\S]*?v-model:value="selectedHistoryFilterKeys"[\s\S]*?<\/ATreeSelect>/,
  )
  const chevronRule = extractRule(historyPageVue, '.history-select-chevron')
  const openChevronRule = extractRule(
    historyPageVue,
    '.history-list :deep(.history-filter-tree.ant-select-open .history-select-chevron)',
  )

  assert.ok(filterBlock)
  assert.ok(treeSelect)
  assert.match(historyPageVue, /import \{ DownOutlined, ReloadOutlined, SearchOutlined \} from '@ant-design\/icons-vue'/)
  assert.match(filterBlock[0], /placeholder="搜索公众号或文章标题"/)
  assert.match(filterBlock[0], /<template #suffixIcon>\s*<SearchOutlined/)
  assert.match(historyPageVue, /const keyword = ref<string \| undefined>\(undefined\)/)
  assert.doesNotMatch(historyPageVue, /const keyword = ref\(''\)/)
  assert.match(historyPageVue, /function normalizeHistoryKeyword\(value: string \| undefined\)/)
  assert.match(historyPageVue, /keyword\.value = undefined/)
  assert.match(historyPageVue, /keyword\.value = normalizeHistoryKeyword\(value\)/)
  assert.match(historyPageVue, /const HISTORY_FILTER_COLLECT_TYPE_KEYS = \['history-filter:type:detail', 'history-filter:type:comments'\]/)
  assert.match(historyPageVue, /const HISTORY_FILTER_STATUS_KEYS = \['history-filter:status:success', 'history-filter:status:failed'\]/)
  assert.match(historyPageVue, /const selectedHistoryFilterKeys = computed<string\[\]>\(\{/)
  assert.match(historyPageVue, /function applyHistoryFilterKeys\(value: string\[\]\)/)
  assert.match(treeSelect[0], /tree-checkable/)
  assert.match(treeSelect[0], /tree-default-expand-all/)
  assert.match(treeSelect[0], /:show-search="false"/)
  assert.match(treeSelect[0], /:max-tag-count="0"/)
  assert.match(treeSelect[0], /:max-tag-placeholder="renderHistoryFilterTagPlaceholder"/)
  assert.match(treeSelect[0], /placeholder="筛选：全部"/)
  assert.match(treeSelect[0], /<DownOutlined[\s\S]*history-select-chevron/)
  assert.match(chevronRule, /transition:\s*transform 160ms ease;/)
  assert.match(chevronRule, /pointer-events:\s*none;/)
  assert.match(openChevronRule, /transform:\s*rotate\(180deg\);/)
})

test('采集历史筛选浮层按应用缩放比例显示', () => {
  const keywordDropdownRule = extractRule(historyPageVue, ':global(.history-keyword-panel.ant-select-dropdown)')
  const filterDropdownRule = extractRule(historyPageVue, ':global(.history-filter-select-panel.ant-select-dropdown)')
  const datePanelRule = historyPageVue.match(
    /:global\(\.history-date-range-picker-panel \.ant-picker-panel-container\)\s*\{[\s\S]*?\n\}/,
  )

  assert.ok(datePanelRule, 'history date picker panel scale rule should exist')
  assert.match(keywordDropdownRule, /min-width:\s*calc\(180px \* var\(--app-scale\)\);/)
  assert.match(keywordDropdownRule, /font-size:\s*calc\(14px \* var\(--app-scale\)\);/)
  assert.match(filterDropdownRule, /font-size:\s*calc\(14px \* var\(--app-scale\)\);/)
  assert.match(datePanelRule[0], /zoom:\s*var\(--app-scale\);/)
})

test('采集历史树筛选浮层参考搜索框做紧凑缩放', () => {
  const panelRule = extractRule(historyPageVue, ':global(.history-filter-select-panel.ant-select-dropdown)')
  const treeRule = extractRule(historyPageVue, ':global(.history-filter-select-panel .ant-select-tree)')
  const treeNodeRule = extractRule(historyPageVue, ':global(.history-filter-select-panel .ant-select-tree-treenode)')
  const contentRule = extractRule(
    historyPageVue,
    ':global(.history-filter-select-panel .ant-select-tree-node-content-wrapper)',
  )
  const checkboxRule = extractRule(
    historyPageVue,
    ':global(.history-filter-select-panel .ant-select-tree-checkbox-inner)',
  )
  const switcherRule = extractRule(historyPageVue, ':global(.history-filter-select-panel .ant-select-tree-switcher)')
  const indentRule = extractRule(historyPageVue, ':global(.history-filter-select-panel .ant-select-tree-indent-unit)')

  assert.match(panelRule, /min-width:\s*calc\(152px \* var\(--app-scale\)\);/)
  assert.match(panelRule, /max-width:\s*calc\(176px \* var\(--app-scale\)\);/)
  assert.match(treeRule, /font-size:\s*calc\(14px \* var\(--app-scale\)\);/)
  assert.match(treeNodeRule, /min-height:\s*calc\(26px \* var\(--app-scale\)\);/)
  assert.match(contentRule, /min-height:\s*calc\(26px \* var\(--app-scale\)\);/)
  assert.match(contentRule, /line-height:\s*calc\(26px \* var\(--app-scale\)\);/)
  assert.match(checkboxRule, /width:\s*calc\(15px \* var\(--app-scale\)\);/)
  assert.match(checkboxRule, /height:\s*calc\(15px \* var\(--app-scale\)\);/)
  assert.match(switcherRule, /width:\s*calc\(18px \* var\(--app-scale\)\);/)
  assert.match(indentRule, /width:\s*calc\(14px \* var\(--app-scale\)\);/)
})

test('采集历史表格和分页使用 Ant Design Vue 并固定 15 行', () => {
  const tableBlock = historyPageVue.match(/<ATable[\s\S]*?class="history-ant-table"[\s\S]*?<\/ATable>/)
  const pagerBlock = historyPageVue.match(/<APagination[\s\S]*?class="history-ant-pager"[\s\S]*?\/>/)
  const tableWrapRule = extractRule(historyPageVue, '.history-table-wrap')
  const tableRule = extractRule(historyPageVue, '.history-list :deep(.history-ant-table .ant-table)')
  const headerRule = extractRule(historyPageVue, '.history-list :deep(.history-ant-table .ant-table-thead > tr > th)')
  const rowRule = extractRule(historyPageVue, '.history-list :deep(.history-ant-table .ant-table-tbody > tr)')
  const cellRule = extractRule(historyPageVue, '.history-list :deep(.history-ant-table .ant-table-tbody > tr > td)')
  const pagerRule = extractRule(historyPageVue, '.history-ant-pagination')

  assert.ok(tableBlock, 'history page should render an Ant Design table')
  assert.ok(pagerBlock, 'history page should render Ant Design pagination')
  assert.match(historyPageVue, /const HISTORY_VISIBLE_ROWS = 15/)
  assert.match(historyPageVue, /const historyPageSize = ref\(HISTORY_VISIBLE_ROWS\)/)
  assert.match(historyPageVue, /const historyTableRows = computed<HistoryTableRow\[\]>\(\(\) =>/)
  assert.match(historyPageVue, /historyPlaceholderRowCount/)
  assert.match(historyPageVue, /new ResizeObserver\(updateHistoryTableMetrics\)/)
  assert.match(tableBlock[0], /:columns="historyTableColumns"/)
  assert.match(tableBlock[0], /:data-source="historyTableRows"/)
  assert.match(tableBlock[0], /:pagination="false"/)
  assert.match(pagerBlock[0], /:page-size-options="\[HISTORY_VISIBLE_ROWS\]"/)
  assert.doesNotMatch(historyPageVue, /VxeGrid|VxePager|VxeTooltip|history-vxe|vxe-/)

  assert.match(tableWrapRule, /--history-body-height:\s*480px;/)
  assert.match(tableWrapRule, /flex:\s*1 1 0;/)
  assert.match(tableWrapRule, /margin-top:\s*6px;/)
  assert.match(tableRule, /font-weight:\s*400;/)
  assert.match(headerRule, /height:\s*var\(--history-header-height\);/)
  assert.match(rowRule, /height:\s*var\(--history-row-height, 32px\);/)
  assert.match(cellRule, /height:\s*var\(--history-row-height, 32px\);/)
  assert.match(pagerRule, /margin-top:\s*6px;/)
})

test('采集历史右侧详情和统计区沿用低刺激纸质层次', () => {
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

  assert.match(historyPageVue, /<ATooltip[\s\S]*?:title=/)
  assert.match(historyPageVue, /<ATag[\s\S]*?class="history-status-tag"/)
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
  const darkTableWrapRule = extractRule(historyPageVue, ':global(.collector-app.dark) .history-table-wrap')
  const darkSelectRule = extractRule(
    historyPageVue,
    ':global(.collector-app.dark) .history-list :deep(.history-ant-select.ant-select .ant-select-selector)',
  )
  const darkEmptyRule = extractRule(historyPageVue, ':global(.collector-app.dark) .detail-empty')

  assert.match(darkTableWrapRule, /background:\s*rgba\(15, 24, 39, 0\.52\);/)
  assert.match(darkSelectRule, /background:\s*rgba\(15, 24, 39, 0\.56\);/)
  assert.match(darkEmptyRule, /background:\s*rgba\(15, 24, 39, 0\.36\);/)
  assert.doesNotMatch(darkSelectRule, /linear-gradient|radial-gradient|backdrop-filter/)
})

test('采集历史统计区域提供清空记录按钮和二次确认弹窗', () => {
  const statsBlock = historyPageVue.match(/<section class="history-stats page-panel">[\s\S]*?<\/section>/)
  const clearButtonRule = extractRule(historyPageVue, '.history-clear-button')

  assert.ok(statsBlock, 'history stats block should exist')
  assert.match(statsBlock[0], /history-stats-header/)
  assert.match(statsBlock[0], /class="history-clear-button"/)
  assert.match(statsBlock[0], /danger/)
  assert.match(statsBlock[0], /@click="openClearHistoryDialog"/)
  assert.match(historyPageVue, /<AModal[\s\S]*class="history-clear-modal"/)
  assert.match(historyPageVue, /title="清空采集历史"/)
  assert.match(historyPageVue, /ok-text="确认清空"/)
  assert.match(historyPageVue, /cancel-text="取消"/)
  assert.match(historyPageVue, /不会删除文章归档和公众号数据/)
  assert.match(historyPageVue, /async function confirmClearHistory\(\)/)
  assert.match(historyPageVue, /clearHistoryRecords\(\)/)
  assert.match(clearButtonRule, /border-color:\s*rgba\(217, 65, 63, 0\.24\);/)
})
