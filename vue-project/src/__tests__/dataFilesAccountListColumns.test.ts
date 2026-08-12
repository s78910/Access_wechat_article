import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const currentDir = dirname(fileURLToPath(import.meta.url))
const pageSource = readFileSync(resolve(currentDir, '../pages/DataFilesPage.vue'), 'utf8')

test('公众号列表采集列显示日期且数量列只显示数字', () => {
  const accountTableMatch = pageSource.match(/<table class="data-table account-table">[\s\S]*?<\/table>/)

  assert.ok(accountTableMatch, '公众号列表表格应该存在')

  const accountTable = accountTableMatch[0]

  assert.match(accountTable, /<th>采集时间<\/th>/)
  assert.match(accountTable, /<th>数量<\/th>/)
  assert.match(pageSource, /function formatAccountCollectDate\(value: string\)/)
  assert.match(pageSource, /createdAt: formatAccountCollectDate\(latestCollectTime\)/)
  assert.match(accountTable, /<td>\{\{ file\.articleCount \}\}<\/td>/)
  assert.doesNotMatch(accountTable, /<th>采集更新时间<\/th>/)
  assert.doesNotMatch(accountTable, /<th>大小<\/th>/)
  assert.doesNotMatch(accountTable, /articleCount\} 条/)
  assert.doesNotMatch(accountTable, /<td>\{\{ file\.size \}\}<\/td>/)
})
