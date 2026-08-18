import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import test from 'node:test'

const currentDir = dirname(fileURLToPath(import.meta.url))
const pageSource = readFileSync(resolve(currentDir, '../pages/DataFilesPage.vue'), 'utf-8')

test('数据档案记录详情展示文章发布时间，不再把采集时间作为优先展示值', () => {
  assert.match(pageSource, /title: '文章发布时间'/)
  assert.match(pageSource, /publishedAt:\s*item\.publishedArticleTime\s*\|\|\s*'-'/)
  assert.doesNotMatch(pageSource, /collectedAt:\s*item\.collectTime\s*\|\|\s*item\.publishedArticleTime/)
})
