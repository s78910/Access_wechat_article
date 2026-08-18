import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const currentDir = dirname(fileURLToPath(import.meta.url))
const dataFilesPageVue = readFileSync(resolve(currentDir, '../pages/DataFilesPage.vue'), 'utf8')

function extractRule(source: string, selector: string) {
  const normalizedSource = source.replace(/\r\n/g, '\n')
  const escaped = selector.replace(/[.*+?^$()|[\]\\]/g, '\\$&')
  const match = normalizedSource.match(new RegExp(escaped + '\\s*\\{[\\s\\S]*?\\n\\}'))

  assert.ok(match, selector + ' rule should exist')

  return match[0]
}

test('记录详情操作区并入标题右侧且表格贴近标题行', () => {
  const recordDetailRule = extractRule(dataFilesPageVue, '.record-detail')
  const recordHeaderRule = extractRule(dataFilesPageVue, '.record-detail-header')
  const recordActionsRule = extractRule(dataFilesPageVue, '.record-actions')
  const recordAccountNameRule = extractRule(dataFilesPageVue, '.record-account-name')
  const recordPrimaryActionRule = extractRule(dataFilesPageVue, '.record-actions .action-button.primary')
  const recordDangerActionRule = extractRule(dataFilesPageVue, '.record-actions .action-button.danger')
  const accountTableWrapRule = extractRule(dataFilesPageVue, '.file-list .table-wrap')
  const recordTableWrapRule = extractRule(dataFilesPageVue, '.record-table-wrap')
  const recordTableHeadRule = extractRule(dataFilesPageVue, '.record-table :deep(.ant-table-thead > tr > th)')
  const recordPaginationRule = extractRule(dataFilesPageVue, '.record-pagination')
  const recordPaginationTotalRule = extractRule(dataFilesPageVue, '.record-pagination-total')
  const recordPagerRule = extractRule(dataFilesPageVue, '.record-detail :deep(.record-ant-pager.ant-pagination)')

  assert.match(
    dataFilesPageVue,
    /<div class="record-detail-header">[\s\S]*?<h2 class="section-heading">[\s\S]*?<div\s+v-if="selectedPreviewFile"\s+class="record-actions"/,
  )
  assert.match(recordDetailRule, /display:\s*grid;/)
  assert.match(recordDetailRule, /grid-template-rows:\s*auto minmax\(0, 1fr\) auto;/)
  assert.match(recordDetailRule, /row-gap:\s*4px;/)
  assert.match(recordDetailRule, /min-height:\s*0;/)
  assert.match(recordHeaderRule, /display:\s*grid;/)
  assert.match(recordHeaderRule, /grid-template-columns:\s*max-content minmax\(0, 1fr\);/)
  assert.match(recordHeaderRule, /align-items:\s*center;/)
  assert.match(recordHeaderRule, /gap:\s*24px;/)
  assert.match(recordHeaderRule, /min-height:\s*36px;/)
  assert.match(dataFilesPageVue, /<span class="record-account-name">\{\{ selectedPreviewFile\.account \}\}<\/span>/)
  assert.doesNotMatch(dataFilesPageVue, /<span>当前 \{\{ selectedPreviewFile\.account \}\}<\/span>/)
  assert.doesNotMatch(dataFilesPageVue, /record-selection-summary[\s\S]*?<span>共 \{\{ recordPagerTotal \}\} 条<\/span>/)
  assert.match(recordAccountNameRule, /font-weight:\s*700;/)
  assert.match(recordActionsRule, /justify-self:\s*end;/)
  assert.match(recordActionsRule, /margin-top:\s*0;/)
  assert.doesNotMatch(recordPrimaryActionRule, /radial-gradient|linear-gradient|inset\s+0\s+1px/)
  assert.doesNotMatch(recordDangerActionRule, /radial-gradient|linear-gradient|inset\s+0\s+1px/)
  assert.doesNotMatch(recordTableWrapRule, /height:\s*auto;/)
  assert.match(recordTableWrapRule, /align-self:\s*stretch;/)
  assert.match(recordTableWrapRule, /margin-top:\s*8px;/)
  assert.match(accountTableWrapRule, /height:\s*calc\(var\(--archive-table-header-height\) \+ var\(--archive-table-body-height\)\);/)
  assert.match(recordTableWrapRule, /height:\s*calc\(var\(--archive-table-header-height\) \+ var\(--archive-table-body-height\)\);/)
  assert.doesNotMatch(dataFilesPageVue, /ref="recordTableWrapRef"/)
  assert.match(dataFilesPageVue, /recordPlaceholderRowCount/)
  assert.match(dataFilesPageVue, /table-placeholder-row/)
  assert.doesNotMatch(recordTableHeadRule, /position:\s*sticky;/)
  assert.doesNotMatch(recordTableHeadRule, /top:\s*0;/)
  assert.doesNotMatch(dataFilesPageVue, /record-index/)
  assert.doesNotMatch(dataFilesPageVue, /<table class="data-table record-table">/)
  assert.match(dataFilesPageVue, /<ATable[\s\S]*?class="archive-ant-table record-table"[\s\S]*?:columns="recordTableColumns"/)
  assert.match(dataFilesPageVue, /<template #headerCell="\{ column \}">[\s\S]*?<ACheckbox/)
  assert.match(dataFilesPageVue, /title: '标题'/)
  assert.match(dataFilesPageVue, /makeStateCellAttrs\('selection', 5\)/)
  assert.doesNotMatch(dataFilesPageVue, /makeStateCellAttrs\('selection', 6\)/)
  assert.match(dataFilesPageVue, /<div class="record-pagination" aria-label="记录详情分页">\s*<span class="record-pagination-total">共 \{\{ recordPagerTotal \}\} 条<\/span>/)
  assert.match(recordPaginationRule, /justify-content:\s*space-between;/)
  assert.match(recordPaginationRule, /min-height:\s*40px;/)
  assert.match(recordPaginationTotalRule, /padding-left:\s*8px;/)
  assert.match(recordPaginationTotalRule, /font-weight:\s*400;/)
  assert.match(recordPagerRule, /flex:\s*0 0 auto;/)
  assert.match(recordPagerRule, /width:\s*auto;/)
})
