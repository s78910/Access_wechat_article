import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const currentDir = dirname(fileURLToPath(import.meta.url))
const pageSource = readFileSync(resolve(currentDir, '../pages/DataFilesPage.vue'), 'utf8')

test('公众号列表采集列显示日期且数量列只显示数字', () => {
  const accountTableMatch = pageSource.match(/<ATable[\s\S]*?class="archive-ant-table account-table"[\s\S]*?<\/ATable>/)

  assert.ok(accountTableMatch, '公众号列表 Ant Design Table 应该存在')

  const accountTable = accountTableMatch[0]
  const accountColumnsMatch = pageSource.match(/const accountTableColumns(?::[^=]+)? = \[[\s\S]*?\n\]\n\nconst recordTableColumns/)

  assert.ok(accountColumnsMatch, '公众号列表列配置应该存在')

  const accountColumns = accountColumnsMatch[0]

  assert.match(accountColumns, /title: '采集时间'/)
  assert.match(accountColumns, /title: '数量'/)
  assert.match(pageSource, /function formatAccountCollectDate\(value: string\)/)
  assert.match(pageSource, /createdAt: formatAccountCollectDate\(latestCollectTime\)/)
  assert.match(accountTable, /:data-source="accountTableRows"/)
  assert.match(accountTable, /:pagination="false"/)
  assert.match(accountTable, /\{\{ record\.articleCount \}\}/)
  assert.doesNotMatch(accountColumns, /title: '采集更新时间'/)
  assert.doesNotMatch(accountColumns, /title: '大小'/)
  assert.doesNotMatch(accountTable, /articleCount\} 条/)
  assert.doesNotMatch(accountTable, /\{\{ record\.size \}\}/)
})
