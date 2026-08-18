import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const currentDir = dirname(fileURLToPath(import.meta.url))
const pageSource = readFileSync(resolve(currentDir, '../pages/DataFilesPage.vue'), 'utf8')

test('数据档案页账号筛选复用主服务页日期筛选的 Dropdown 选择器风格', () => {
  assert.match(pageSource, /import \{[^}]*DownOutlined[^}]*\} from '@ant-design\/icons-vue'/)
  assert.match(pageSource, /const selectedAccountDropdownOpen = ref\(false\)/)
  assert.match(pageSource, /const accountFilterOptions = computed\(\(\) => \[/)
  assert.match(pageSource, /const selectedAccountLabel = computed/)
  assert.match(pageSource, /function selectArchiveAccountFilter\(value: string\)/)
  assert.match(pageSource, /<ADropdown[\s\S]*?v-model:open="selectedAccountDropdownOpen"/)
  assert.match(pageSource, /overlay-class-name="file-account-filter-dropdown"/)
  assert.match(pageSource, /class="file-select-trigger account-select-trigger"/)
  assert.match(pageSource, /\{\{ selectedAccountLabel \}\}/)
  assert.match(
    pageSource,
    /<DownOutlined\s+:class="\['file-select-chevron', \{ 'is-open': selectedAccountDropdownOpen \}\]"\s+\/>/,
  )
  assert.match(pageSource, /<AMenu :selected-keys="selectedAccountMenuKeys">/)
  assert.match(pageSource, /<AMenuItem[\s\S]*?v-for="option in accountFilterOptions"/)
  assert.match(pageSource, /@click="selectArchiveAccountFilter\(option\.value\)"/)
  assert.doesNotMatch(pageSource, /<ASelect|<VxeSelect/)

  const triggerRule = pageSource.match(/\.file-select-trigger\s*\{(?<body>[\s\S]*?)\}/)
  const triggerTextRule = pageSource.match(/\.file-select-trigger > span:first-child\s*\{(?<body>[\s\S]*?)\}/)
  const chevronRule = pageSource.match(/\.file-select-chevron\s*\{(?<body>[\s\S]*?)\}/)

  assert.ok(triggerRule?.groups?.body)
  assert.match(triggerRule.groups.body, /height:\s*32px;/)
  assert.match(triggerRule.groups.body, /padding:\s*0 22px 0 4px;/)
  assert.match(triggerRule.groups.body, /overflow:\s*hidden;/)
  assert.ok(triggerTextRule?.groups?.body)
  assert.match(triggerTextRule.groups.body, /min-width:\s*0;/)
  assert.match(triggerTextRule.groups.body, /text-overflow:\s*ellipsis;/)
  assert.ok(chevronRule?.groups?.body)
  assert.match(chevronRule.groups.body, /right:\s*8px;/)
  assert.match(chevronRule.groups.body, /transform:\s*translateY\(-50%\) rotate\(0deg\);/)
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
