import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const currentDir = dirname(fileURLToPath(import.meta.url))
const pageSource = readFileSync(resolve(currentDir, '../pages/DataFilesPage.vue'), 'utf8')

test('公众号列表按 9 个字符加省略号展示长名称', () => {
  assert.match(pageSource, /truncateAccountName/)
  assert.match(pageSource, /slice\(0, 9\)/)
  assert.match(pageSource, /\.\.\./)
  assert.match(pageSource, /account-name-cell/)
})

test('记录详情标题绑定文章短链接并展示可点击光标', () => {
  assert.match(pageSource, /link: item\.articleLink/)
  assert.match(pageSource, /openArticleLink/)
  assert.match(pageSource, /record-title-link/)
  assert.match(pageSource, /cursor: pointer/)
})

test('记录详情增加打开目录操作列', () => {
  assert.match(pageSource, /title: '操作'/)
  assert.match(pageSource, /record-open-col/)
  assert.match(pageSource, /openRecordArchiveDirectory/)
  assert.match(pageSource, /openArchiveArticleDirectory/)
  assert.match(pageSource, /打开目录/)
})

test('记录详情打开目录按钮始终呈现可点击的小手状态', () => {
  assert.doesNotMatch(pageSource, /:disabled="!record\.archiveDir"/)
  assert.match(pageSource, /\.record-open-cell \.text-link \{[\s\S]*cursor: pointer;/)
})
