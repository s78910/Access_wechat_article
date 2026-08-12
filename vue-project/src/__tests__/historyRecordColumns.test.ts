import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const currentDir = dirname(fileURLToPath(import.meta.url))
const pageSource = readFileSync(resolve(currentDir, '../pages/HistoryPage.vue'), 'utf8')

test('采集记录表格将采集时间表头改为记录时间并移除耗时列', () => {
  assert.match(pageSource, /field:\s*'collectTime',\s*title:\s*'记录时间'/)
  assert.doesNotMatch(pageSource, /field:\s*'collectTime',\s*title:\s*'采集时间'/)
  assert.doesNotMatch(pageSource, /field:\s*'duration',\s*title:\s*'耗时'/)
})

test('采集记录表格的公众号列按 9 个字符加省略号展示长名称', () => {
  assert.match(pageSource, /field:\s*'account'[\s\S]*slots:\s*\{\s*default:\s*'account'\s*\}/)
  assert.match(pageSource, /function truncateAccountName\(account: string\)/)
  assert.match(pageSource, /slice\(0, 9\)/)
  assert.match(pageSource, /\.\.\./)
  assert.match(pageSource, /history-account-cell/)
})

test('采集记录表格使用固定列宽，不让记录名称和辅助列自动拉伸', () => {
  assert.match(pageSource, /field:\s*'name'[\s\S]*width:\s*200/)
  assert.match(pageSource, /field:\s*'account'[\s\S]*width:\s*128/)
  assert.match(pageSource, /field:\s*'collectType',\s*title:\s*'采集类型',\s*width:\s*72/)
  assert.match(pageSource, /field:\s*'collectTime',\s*title:\s*'记录时间',\s*width:\s*168/)
  assert.match(pageSource, /field:\s*'status'[\s\S]*width:\s*82/)
  assert.match(pageSource, /title:\s*'操作'[\s\S]*width:\s*52/)
  assert.match(pageSource, /:fit="false"/)
  assert.doesNotMatch(pageSource, /:fit="true"/)
})
