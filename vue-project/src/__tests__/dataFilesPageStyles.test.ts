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
  const tableHeaderRule = extractRule(
    dataFilesPageVue,
    '.files-page :deep(.archive-ant-table .ant-table-thead > tr > th)',
  )
  const tableCellRule = extractRule(
    dataFilesPageVue,
    '.files-page :deep(.archive-ant-table .ant-table-tbody > tr > td)',
  )

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
  const firstRunDescriptionRule = extractRule(dataFilesPageVue, '.record-empty-first-run p')
  const overviewGuideRule = extractRule(dataFilesPageVue, '.archive-overview-guide')
  const overviewGuideTitleRule = extractRule(dataFilesPageVue, '.archive-overview-guide strong')
  const overviewGuideStepsRule = extractRule(dataFilesPageVue, '.archive-overview-guide-steps')
  const overviewGuideStepRule = extractRule(dataFilesPageVue, '.archive-overview-guide-steps span')

  assert.match(headingRule, /font-weight:\s*500;/)
  assert.match(selectionSummaryRule, /border:\s*1px solid var\(--line-soft\);/)
  assert.match(selectionSummaryRule, /background:\s*rgba\(255, 255, 255, 0\.36\);/)
  assert.match(selectionSummaryRule, /font-weight:\s*400;/)
  assert.match(emptyRule, /border:\s*1px dashed rgba\(104, 141, 181, 0\.26\);/)
  assert.match(emptyRule, /background:\s*rgba\(255, 255, 255, 0\.26\);/)
  assert.match(firstRunDescriptionRule, /font-weight:\s*400;/)
  assert.match(overviewGuideRule, /grid-template-columns:\s*32px minmax\(0, 1fr\) auto;/)
  assert.match(overviewGuideRule, /grid-column:\s*1 \/ -1;/)
  assert.match(overviewGuideRule, /background:\s*rgba\(235, 246, 253, 0\.72\);/)
  assert.match(overviewGuideRule, /white-space:\s*normal;/)
  assert.match(overviewGuideTitleRule, /font-size:\s*16px;/)
  assert.match(overviewGuideTitleRule, /font-weight:\s*500;/)
  assert.match(overviewGuideStepsRule, /display:\s*flex;/)
  assert.match(overviewGuideStepsRule, /justify-content:\s*flex-end;/)
  assert.match(overviewGuideStepsRule, /flex-wrap:\s*wrap;/)
  assert.match(overviewGuideStepRule, /background:\s*rgba\(255, 255, 255, 0\.62\);/)
  assert.match(overviewGuideStepRule, /white-space:\s*nowrap;/)
  assert.match(dataFilesPageVue, /<ASkeleton[\s\S]*active/)
  assert.match(dataFilesPageVue, /<AResult[\s\S]*title="读取归档数据失败"/)
  assert.match(dataFilesPageVue, /<ArchiveDistributionChart[\s\S]*:data="archiveDistributionData"/)
  assert.doesNotMatch(dataFilesPageVue, /<AEmpty/)
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
  assert.match(
    dataFilesPageVue,
    /:global\(\.collector-app\.dark\) \.record-empty-result :deep\(\.ant-result-title\),[\s\S]*?color:\s*#dce7f5;/,
  )
  assert.match(
    dataFilesPageVue,
    /:global\(\.collector-app\.dark\) \.record-empty-first-run p,[\s\S]*?\.archive-overview-guide-copy > span,[\s\S]*?color:\s*#9fb2cc;/,
  )
  assert.match(
    dataFilesPageVue,
    /:global\(\.collector-app\.dark\) \.record-overview-empty\s*\{[\s\S]*?background:\s*transparent;/,
  )
  assert.match(
    dataFilesPageVue,
    /:global\(\.collector-app\.dark\) \.archive-overview-guide\s*\{[\s\S]*?background:\s*rgba\(31, 52, 80, 0\.54\);/,
  )
  assert.match(
    dataFilesPageVue,
    /:global\(\.collector-app\.dark\) \.archive-overview-guide-steps span\s*\{[\s\S]*?background:\s*rgba\(15, 24, 39, 0\.5\);/,
  )
})

test('archive metric cards keep the original article layout', () => {
  const cardRule = extractRule(dataFilesPageVue, '.files-metrics > .metric-card')

  assert.match(dataFilesPageVue, /<article v-for="item in archiveMetrics"/)
  assert.match(cardRule, /height:\s*72px;/)
  assert.match(cardRule, /min-width:\s*0;/)
  assert.match(cardRule, /overflow:\s*hidden;/)
  assert.doesNotMatch(dataFilesPageVue, /\.files-metrics[^\n]*ant-card-body/)
})

test('archive filters reserve a compact first column for the refresh button', () => {
  const filtersRule = extractRule(dataFilesPageVue, '.file-filters')
  const refreshButtonRule = extractRule(dataFilesPageVue, '.file-refresh-button')

  assert.match(
    filtersRule,
    /grid-template-columns:\s*72px minmax\(0, 110px\) minmax\(0, 1fr\);/,
  )
  assert.match(filtersRule, /width:\s*min\(100%, 520px\);/)
  assert.match(refreshButtonRule, /width:\s*72px;/)
  assert.match(refreshButtonRule, /height:\s*32px;/)
  assert.match(refreshButtonRule, /justify-content:\s*center;/)
})
