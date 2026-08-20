import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const currentDir = dirname(fileURLToPath(import.meta.url))
const pageSource = readFileSync(resolve(currentDir, '../pages/DataFilesPage.vue'), 'utf8')

test('数据档案页账号筛选复用采集历史页搜索输入框式 Select 交互', () => {
  assert.match(pageSource, /import \{[^}]*SearchOutlined[^}]*\} from '@ant-design\/icons-vue'/)
  assert.match(pageSource, /const accountSelectOptions = computed(?:<[^>]+>)?\(\(\) =>/)
  assert.match(pageSource, /<ASelect[\s\S]*?v-model:value="selectedAccount"/)
  assert.match(pageSource, /class="file-ant-control file-ant-select account-select-trigger"/)
  assert.match(pageSource, /show-search/)
  assert.match(pageSource, /allow-clear/)
  assert.match(pageSource, /placeholder="选择公众号"/)
  assert.match(pageSource, /:options="accountSelectOptions"/)
  assert.match(pageSource, /:filter-option="filterArchiveAccountOption"/)
  assert.match(pageSource, /:dropdown-match-select-width="false"/)
  assert.match(pageSource, /popup-class-name="file-account-filter-dropdown"/)
  assert.match(pageSource, /<template #suffixIcon>[\s\S]*?<SearchOutlined class="file-search-icon" \/>[\s\S]*?<\/template>/)
  assert.doesNotMatch(pageSource, /selectedAccountDropdownOpen|selectedAccountLabel|selectedAccountMenuKeys/)
  assert.doesNotMatch(pageSource, /<ADropdown|<AMenu|<AMenuItem|<VxeSelect/)

  const selectorRule = pageSource.match(/\.file-list :deep\(\.file-ant-select\.ant-select \.ant-select-selector\)\s*\{(?<body>[\s\S]*?)\}/)
  const textRule = pageSource.match(/\.file-list :deep\(\.file-ant-select\.ant-select \.ant-select-selection-item\),[\s\S]*?\.file-list :deep\(\.file-ant-select\.ant-select \.ant-select-selection-search-input\)\s*\{(?<body>[\s\S]*?)\}/)
  const iconRule = pageSource.match(/\.file-search-icon\s*\{(?<body>[\s\S]*?)\}/)

  assert.ok(selectorRule?.groups?.body)
  assert.match(selectorRule.groups.body, /height:\s*32px;/)
  assert.match(selectorRule.groups.body, /padding:\s*0 11px;/)
  assert.match(selectorRule.groups.body, /border-radius:\s*6px;/)
  assert.ok(textRule?.groups?.body)
  assert.match(textRule.groups.body, /font-size:\s*14px;/)
  assert.match(textRule.groups.body, /line-height:\s*30px;/)
  assert.ok(iconRule?.groups?.body)
  assert.match(iconRule.groups.body, /font-size:\s*14px;/)

  const dropdownRule = pageSource.match(/:global\(\.file-account-filter-dropdown\.ant-select-dropdown\)\s*\{(?<body>[\s\S]*?)\}/)

  assert.ok(dropdownRule?.groups?.body)
  assert.match(dropdownRule.groups.body, /width:\s*max-content;/)
  assert.match(dropdownRule.groups.body, /min-width:\s*calc\(240px \* var\(--app-scale\)\);/)
  assert.match(dropdownRule.groups.body, /max-width:\s*calc\(360px \* var\(--app-scale\)\);/)
  assert.match(dropdownRule.groups.body, /border:\s*1px solid var\(--line\);/)
  assert.doesNotMatch(dropdownRule.groups.body, /zoom:\s*var\(--app-scale\);/)

  const optionContentRule = pageSource.match(/:global\(\.file-account-filter-dropdown\.ant-select-dropdown \.ant-select-item-option-content\)\s*\{(?<body>[\s\S]*?)\}/)

  assert.ok(optionContentRule?.groups?.body)
  assert.match(optionContentRule.groups.body, /overflow:\s*visible;/)
  assert.match(optionContentRule.groups.body, /text-overflow:\s*clip;/)
})

test('数据档案页采集日期恢复为 Ant Design RangePicker 并使用主服务页日历弹层策略', () => {
  assert.match(pageSource, /type CollectDateRangeValue = \[string, string\] \| null/)
  assert.match(pageSource, /const selectedCollectDateRange = computed<CollectDateRangeValue>/)
  assert.match(pageSource, /<ARangePicker[\s\S]*?v-model:value="selectedCollectDateRange"/)
  assert.match(pageSource, /class="file-date-picker file-date-range-picker"/)
  assert.match(pageSource, /format="YYYY-MM-DD"/)
  assert.match(pageSource, /value-format="YYYY-MM-DD"/)
  assert.match(pageSource, /popup-class-name="file-date-picker-panel"/)
  assert.match(
    pageSource,
    /:global\(\.file-date-picker-panel \.ant-picker-panel-container\)\s*\{[\s\S]*?zoom:\s*var\(--app-scale\);/,
  )
  const pickerRule = pageSource.match(/\.file-date-picker\s*\{(?<body>[\s\S]*?)\}/)
  const antPickerRule = pageSource.match(/\.file-list :deep\(\.file-date-picker\.ant-picker\)\s*\{(?<body>[\s\S]*?)\}/)

  assert.ok(pickerRule?.groups?.body)
  assert.match(pickerRule.groups.body, /height:\s*32px;/)
  assert.ok(antPickerRule?.groups?.body)
  assert.match(antPickerRule.groups.body, /height:\s*32px;/)
  assert.match(antPickerRule.groups.body, /padding-inline:\s*12px;/)
  assert.doesNotMatch(pageSource, /<VxeDateRangePicker/)
  assert.doesNotMatch(pageSource, /getArchiveFilterPopupContainer|get-popup-container/)
})

test('数据档案页分页、操作按钮和勾选框继续使用 Ant Design Vue 控件', () => {
  assert.match(pageSource, /<APagination\s+[\s\S]*?class="file-ant-pager"/)
  assert.match(pageSource, /<APagination\s+[\s\S]*?class="file-ant-pager record-ant-pager"/)
  assert.match(pageSource, /<AButton\s+class="text-link"/)
  assert.match(pageSource, /<AButton\s+[\s\S]*class="action-button primary"/)
  assert.match(pageSource, /<AButton\s+[\s\S]*class="action-button ghost"/)
  assert.match(pageSource, /<ACheckbox\s+[\s\S]*class="record-checkbox"/)
  assert.doesNotMatch(pageSource, /<VxePager/)
})

test('数据档案页保留原状态卡片并统一其他展示与反馈控件', () => {
  assert.match(pageSource, /import \{ notification \} from 'ant-design-vue'/)
  assert.match(pageSource, /import ArchiveDistributionChart from '..\/components\/ArchiveDistributionChart\.vue'/)
  assert.match(pageSource, /<article v-for="item in archiveMetrics"/)
  assert.match(pageSource, /<article class="cache-task-status-card metric-card page-panel"/)
  assert.match(pageSource, /<article[\s\S]*?class="cache-active-process-card metric-card page-panel"/)
  assert.match(pageSource, /<ASkeleton[\s\S]*active/)
  assert.match(pageSource, /<AResult[\s\S]*class="record-empty record-empty-result"/)
  assert.match(pageSource, /<ArchiveDistributionChart[\s\S]*:data="archiveDistributionData"/)
  assert.doesNotMatch(pageSource, /<AEmpty/)
  assert.match(pageSource, /<AButton[\s\S]*class="record-title-link"[\s\S]*type="link"/)
  assert.match(pageSource, /<AModal[\s\S]*class="batch-export-modal"/)
  assert.match(pageSource, /<ATable[\s\S]*class="archive-ant-table batch-export-ant-table"/)
  assert.match(pageSource, /<AModal[\s\S]*class="archive-delete-modal"/)
  assert.doesNotMatch(pageSource, /<ACard[^>]*metric-card/)
  assert.doesNotMatch(pageSource, /<button[\s\S]*class="record-title-link"/)
  assert.doesNotMatch(pageSource, /archive-toast-stack|cacheToasts|<ConfirmDialog/)
})

test('数据档案页刷新按钮同步刷新公众号列表和当前记录详情', () => {
  assert.match(pageSource, /import \{[^}]*ReloadOutlined[^}]*\} from '@ant-design\/icons-vue'/)
  assert.match(pageSource, /async function handleRefreshArchiveData\(\)/)
  assert.match(pageSource, /const selectedFileId = selectedPreviewFile\.value\?\.id/)
  assert.match(pageSource, /await loadArchiveAccounts\(\)/)
  assert.match(pageSource, /fileListRows\.value\.find\(\(file\) => file\.id === selectedFileId\)/)
  assert.match(pageSource, /selectedPreviewFile\.value = refreshedFile/)
  assert.match(
    pageSource,
    /await loadArchiveArticles\(refreshedFile, recordCurrentPage\.value, recordPageSize\.value\)/,
  )
  assert.match(
    pageSource,
    /<AButton[\s\S]*?class="file-refresh-button"[\s\S]*?:loading="archiveAccountsLoading \|\| archiveArticlesLoading"[\s\S]*?@click="handleRefreshArchiveData"[\s\S]*?<ReloadOutlined \/>[\s\S]*?刷新[\s\S]*?<\/AButton>/,
  )
})
