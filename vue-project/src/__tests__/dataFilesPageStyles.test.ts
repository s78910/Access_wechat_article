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

test('数据档案页筛选区并入标题行且表格保持轻纸质感容器', () => {
  const fileFiltersRule = extractRule(dataFilesPageVue, '.file-filters')
  const tableSurfaceRule = extractRule(
    dataFilesPageVue,
    '.file-list .table-wrap,\n.record-table-wrap,\n.batch-export-table-wrap',
  )
  const tableHeaderRule = extractRule(dataFilesPageVue, '.files-page .data-table th')
  const tableCellRule = extractRule(dataFilesPageVue, '.files-page .data-table td')

  assert.match(fileFiltersRule, /padding:\s*0;/)
  assert.match(fileFiltersRule, /margin-top:\s*0;/)
  assert.match(fileFiltersRule, /border:\s*0;/)
  assert.match(fileFiltersRule, /background:\s*transparent;/)
  assert.match(fileFiltersRule, /box-shadow:\s*none;/)

  assert.match(tableSurfaceRule, /border:\s*1px solid rgba\(104, 141, 181, 0\.18\);/)
  assert.match(tableSurfaceRule, /background:\s*rgba\(255, 255, 255, 0\.38\);/)
  assert.match(tableSurfaceRule, /box-shadow:\s*inset 0 1px 0 rgba\(255, 255, 255, 0\.58\);/)

  assert.match(tableHeaderRule, /background:\s*rgba\(234, 244, 251, 0\.48\);/)
  assert.match(tableHeaderRule, /font-weight:\s*500;/)
  assert.match(tableCellRule, /font-weight:\s*400;/)
})

test('数据档案页底部快速操作按钮移除玻璃蒙版和装饰特效', () => {
  const bottomQuickButtonRule = extractRule(dataFilesPageVue, '.bottom-quick-grid .action-button')
  const bottomQuickHoverRule = extractRule(
    dataFilesPageVue,
    '.bottom-quick-grid .action-button:hover:not(:disabled)',
  )
  const bottomQuickDangerRule = extractRule(dataFilesPageVue, '.bottom-quick-grid .action-button.danger')

  assert.match(bottomQuickButtonRule, /background:\s*rgba\(255, 255, 255, 0\.5\);/)
  assert.match(bottomQuickButtonRule, /box-shadow:\s*var\(--paper-shadow-sm\);/)
  assert.match(bottomQuickButtonRule, /font-weight:\s*500;/)
  assert.doesNotMatch(bottomQuickButtonRule, /backdrop-filter|radial-gradient|linear-gradient|transform:/)

  assert.match(bottomQuickHoverRule, /transform:\s*none;/)
  assert.match(bottomQuickHoverRule, /box-shadow:\s*var\(--paper-shadow-sm\);/)
  assert.doesNotMatch(bottomQuickHoverRule, /radial-gradient|linear-gradient|backdrop-filter/)

  assert.match(bottomQuickDangerRule, /background:\s*rgba\(255, 241, 241, 0\.76\);/)
  assert.doesNotMatch(bottomQuickDangerRule, /radial-gradient|linear-gradient|backdrop-filter/)
})

test('数据档案页详情区和空状态降低字重并保持纸质层次', () => {
  const headingRule = extractRule(dataFilesPageVue, '.files-page .section-heading')
  const selectionSummaryRule = extractRule(dataFilesPageVue, '.record-selection-summary')
  const emptyRule = extractRule(dataFilesPageVue, '.record-empty')
  const emptyStrongRule = extractRule(dataFilesPageVue, '.record-empty strong')
  const emptySpanRule = extractRule(dataFilesPageVue, '.record-empty span')

  assert.match(headingRule, /font-weight:\s*500;/)
  assert.match(selectionSummaryRule, /border:\s*1px solid var\(--line-soft\);/)
  assert.match(selectionSummaryRule, /background:\s*rgba\(255, 255, 255, 0\.36\);/)
  assert.match(selectionSummaryRule, /font-weight:\s*400;/)
  assert.match(emptyRule, /border:\s*1px dashed rgba\(104, 141, 181, 0\.26\);/)
  assert.match(emptyRule, /background:\s*rgba\(255, 255, 255, 0\.26\);/)
  assert.match(emptyStrongRule, /font-weight:\s*500;/)
  assert.match(emptySpanRule, /font-weight:\s*400;/)
})

test('数据档案页表格内操作链接收敛为轻量按钮样式', () => {
  const tableLinkRule = extractRule(
    dataFilesPageVue,
    '.account-table .text-link,\n.record-open-cell .text-link',
  )
  const tableLinkHoverRule = extractRule(
    dataFilesPageVue,
    '.account-table .text-link:hover:not(:disabled),\n.record-open-cell .text-link:hover:not(:disabled)',
  )
  const titleLinkRule = extractRule(dataFilesPageVue, '.record-title-link')
  const titleLinkHoverRule = extractRule(dataFilesPageVue, '.record-title-link:hover:not(:disabled)')

  assert.match(tableLinkRule, /min-height:\s*26px;/)
  assert.match(tableLinkRule, /border-radius:\s*6px;/)
  assert.match(tableLinkRule, /background:\s*rgba\(45, 117, 214, 0\.08\);/)
  assert.match(tableLinkRule, /text-decoration:\s*none;/)
  assert.match(tableLinkHoverRule, /background:\s*rgba\(45, 117, 214, 0\.14\);/)
  assert.match(titleLinkRule, /font-weight:\s*400;/)
  assert.match(titleLinkHoverRule, /text-decoration:\s*none;/)
})

test('数据档案页暗色主题同步使用低刺激纸质层', () => {
  assert.match(
    dataFilesPageVue,
    /:global\(\.collector-app\.dark\) \.file-filters\s*\{[\s\S]*?background:\s*transparent;/,
  )
  assert.match(
    dataFilesPageVue,
    /:global\(\.collector-app\.dark\) \.file-list \.table-wrap,[\s\S]*?background:\s*rgba\(15, 24, 39, 0\.52\);/,
  )
  assert.match(
    dataFilesPageVue,
    /:global\(\.collector-app\.dark\) \.record-empty\s*\{[\s\S]*?background:\s*rgba\(15, 24, 39, 0\.36\);/,
  )
})
