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
  const recordTableWrapRule = extractRule(dataFilesPageVue, '.record-table-wrap')
  const recordTableHeadRule = extractRule(dataFilesPageVue, '.record-table th')
  const recordPaginationRule = extractRule(dataFilesPageVue, '.record-pagination')
  const recordPaginationTotalRule = extractRule(dataFilesPageVue, '.record-pagination-total')
  const recordPagerRule = extractRule(dataFilesPageVue, '.record-detail :deep(.record-vxe-pager.vxe-pager)')

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
  assert.match(recordHeaderRule, /min-height:\s*48px;/)
  assert.match(dataFilesPageVue, /<span class="record-account-name">\{\{ selectedPreviewFile\.account \}\}<\/span>/)
  assert.doesNotMatch(dataFilesPageVue, /<span>当前 \{\{ selectedPreviewFile\.account \}\}<\/span>/)
  assert.doesNotMatch(dataFilesPageVue, /record-selection-summary[\s\S]*?<span>共 \{\{ recordPagerTotal \}\} 条<\/span>/)
  assert.match(recordAccountNameRule, /font-weight:\s*700;/)
  assert.match(recordActionsRule, /justify-self:\s*end;/)
  assert.match(recordActionsRule, /margin-top:\s*0;/)
  assert.match(recordTableWrapRule, /height:\s*auto;/)
  assert.match(recordTableWrapRule, /align-self:\s*stretch;/)
  assert.match(recordTableWrapRule, /margin-top:\s*8px;/)
  assert.match(dataFilesPageVue, /ref="recordTableWrapRef"/)
  assert.match(dataFilesPageVue, /recordPlaceholderRowCount/)
  assert.match(dataFilesPageVue, /class="table-placeholder-row"/)
  assert.doesNotMatch(recordTableHeadRule, /position:\s*sticky;/)
  assert.doesNotMatch(recordTableHeadRule, /top:\s*0;/)
  assert.doesNotMatch(dataFilesPageVue, /record-index/)
  assert.doesNotMatch(dataFilesPageVue, /<table class="data-table record-table">[\s\S]*?<th>序号<\/th>/)
  assert.match(dataFilesPageVue, /<table class="data-table record-table">[\s\S]*?<th>标题<\/th>/)
  assert.match(dataFilesPageVue, /<td class="table-state-cell" colspan="5">/)
  assert.doesNotMatch(dataFilesPageVue, /<td class="table-state-cell" colspan="6">/)
  assert.match(dataFilesPageVue, /<div class="record-pagination" aria-label="记录详情分页">\s*<span class="record-pagination-total">共 \{\{ recordPagerTotal \}\} 条<\/span>/)
  assert.match(recordPaginationRule, /justify-content:\s*space-between;/)
  assert.match(recordPaginationRule, /min-height:\s*40px;/)
  assert.match(recordPaginationTotalRule, /padding-left:\s*8px;/)
  assert.match(recordPaginationTotalRule, /font-weight:\s*400;/)
  assert.match(recordPagerRule, /flex:\s*0 0 auto;/)
  assert.match(recordPagerRule, /width:\s*auto;/)
})
