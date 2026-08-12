import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const currentDir = dirname(fileURLToPath(import.meta.url))
const pageSource = readFileSync(resolve(currentDir, '../pages/DataFilesPage.vue'), 'utf8')

test('快速操作批量导出按钮打开公众号选择弹窗', () => {
  assert.match(pageSource, /openBatchExportDialog/)
  assert.match(pageSource, /批量导出/)
  assert.match(pageSource, /batch-export-dialog/)
  assert.match(pageSource, /已有公众号列表/)
})

test('批量导出弹窗展示公众号表格和底部操作按钮', () => {
  assert.match(pageSource, /<th class="export-check-col">/)
  assert.match(pageSource, />序号</)
  assert.match(pageSource, />公众号</)
  assert.match(pageSource, />记录数</)
  assert.match(pageSource, /导出为excel/)
  assert.match(pageSource, /closeBatchExportDialog/)
})

test('批量导出按钮直接使用配置的文章存储目录', () => {
  assert.doesNotMatch(pageSource, /selectArchiveExportDirectory/)
  assert.match(pageSource, /exportArchiveAccountsToExcel/)
  assert.match(pageSource, /archiveExporting/)
  assert.match(pageSource, /正在导出/)
  assert.match(pageSource, /spin-icon/)
  assert.doesNotMatch(pageSource, /Excel 导出接口待接入/)
})

test('批量导出失败时保留弹窗并显示错误提示', () => {
  assert.match(pageSource, /if \(!result\.ok\)/)
  assert.match(pageSource, /result\.message \|\| '导出 Excel 失败'/)
  assert.match(pageSource, /showCacheToast\(message, 'error'\)/)
})
