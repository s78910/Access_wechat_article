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

test('公众号列表表格列宽和操作按钮完整显示', () => {
  const filesPageRule = extractRule(dataFilesPageVue, '.files-page')
  const fileListRule = extractRule(dataFilesPageVue, '.file-list')
  const fileListHeaderRule = extractRule(dataFilesPageVue, '.file-list-header')
  const tableWrapRule = extractRule(dataFilesPageVue, '.file-list .table-wrap')
  const nameColRule = extractRule(dataFilesPageVue, '.account-name-col')
  const timeColRule = extractRule(dataFilesPageVue, '.account-time-col')
  const sizeColRule = extractRule(dataFilesPageVue, '.account-size-col')
  const actionColRule = extractRule(dataFilesPageVue, '.account-action-col')
  const actionButtonsRule = extractRule(dataFilesPageVue, '.account-table .table-actions')
  const actionLinkRule = extractRule(dataFilesPageVue, '.account-table .text-link')
  const paginationBarRule = extractRule(dataFilesPageVue, '.file-list .pagination-bar')
  const paginationTotalRule = extractRule(dataFilesPageVue, '.account-pagination-total')
  const accountPagerRule = extractRule(dataFilesPageVue, '.file-list .pagination-bar :deep(.file-vxe-pager.vxe-pager)')
  const accountPagerWrapperRule = extractRule(dataFilesPageVue, '.file-list .pagination-bar :deep(.file-vxe-pager .vxe-pager--wrapper)')

  assert.match(filesPageRule, /grid-template-columns:\s*repeat\(2, minmax\(0, 1fr\)\);/)
  assert.match(fileListRule, /display:\s*grid;/)
  assert.match(fileListRule, /grid-template-rows:\s*auto minmax\(0, 1fr\) auto;/)
  assert.match(fileListRule, /row-gap:\s*4px;/)
  assert.match(fileListRule, /min-height:\s*0;/)
  assert.match(fileListHeaderRule, /display:\s*grid;/)
  assert.match(fileListHeaderRule, /grid-template-columns:\s*max-content minmax\(0, 1fr\);/)
  assert.match(fileListHeaderRule, /align-items:\s*center;/)
  assert.match(fileListHeaderRule, /gap:\s*24px;/)
  assert.match(fileListHeaderRule, /min-height:\s*48px;/)
  assert.match(dataFilesPageVue, /<div class="file-list-header">[\s\S]*?<h2 class="section-heading">[\s\S]*?<div class="filters-row file-filters">/)
  assert.match(tableWrapRule, /height:\s*auto;/)
  assert.match(tableWrapRule, /align-self:\s*stretch;/)
  assert.match(tableWrapRule, /margin-top:\s*8px;/)
  assert.match(dataFilesPageVue, /ref="accountTableWrapRef"/)
  assert.match(dataFilesPageVue, /filePlaceholderRowCount/)
  assert.match(dataFilesPageVue, /class="table-placeholder-row"/)
  assert.match(nameColRule, /width:\s*22%;/)
  assert.match(timeColRule, /width:\s*26%;/)
  assert.match(sizeColRule, /width:\s*9%;/)
  assert.match(actionColRule, /width:\s*220px;/)
  assert.match(actionButtonsRule, /gap:\s*6px;/)
  assert.match(actionButtonsRule, /flex-wrap:\s*nowrap;/)
  assert.match(actionLinkRule, /min-width:\s*50px;/)
  assert.match(actionLinkRule, /padding:\s*0 6px;/)
  assert.match(dataFilesPageVue, /const filePageSize = ref\(10\)/)
  assert.match(dataFilesPageVue, /:page-sizes="\[10\]"/)
  assert.match(dataFilesPageVue, /<span class="account-pagination-total">共 \{\{ filePagerTotal \}\} 条<\/span>/)
  assert.match(paginationBarRule, /min-height:\s*40px;/)
  assert.match(paginationBarRule, /padding-top:\s*4px;/)
  assert.match(paginationBarRule, /padding-left:\s*0;/)
  assert.match(paginationBarRule, /padding-right:\s*0;/)
  assert.match(paginationBarRule, /margin-top:\s*0;/)
  assert.match(paginationBarRule, /width:\s*100%;/)
  assert.match(paginationBarRule, /box-sizing:\s*border-box;/)
  assert.match(accountPagerRule, /flex:\s*0 0 auto;/)
  assert.match(accountPagerRule, /width:\s*auto;/)
  assert.match(accountPagerWrapperRule, /width:\s*auto;/)
  assert.match(paginationTotalRule, /padding-left:\s*8px;/)
})
