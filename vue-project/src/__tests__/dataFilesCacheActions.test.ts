import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const currentDir = dirname(fileURLToPath(import.meta.url))
const pageSource = readFileSync(resolve(currentDir, '../pages/DataFilesPage.vue'), 'utf8')

test('数据档案页把记录详情缓存按钮接到选中文章缓存动作', () => {
  assert.match(pageSource, /cacheSelectedRecords/)
  assert.match(pageSource, /cacheArchiveArticles/)
  assert.match(pageSource, /getArchiveCacheJob/)
  assert.match(pageSource, /@click="cacheSelectedRecords"/)
  assert.match(pageSource, /selectedRecordCount === 0 \|\| archiveCaching/)
})

test('数据档案页把公众号一键缓存接到账号批量缓存动作', () => {
  assert.match(pageSource, /cacheAccountArticles\(record\)/)
  assert.match(pageSource, /cacheArchiveAccount/)
  assert.match(pageSource, /一键缓存/)
  assert.match(pageSource, /:disabled="archiveCaching"/)
})

test('数据档案页缓存任务完成后使用右下角文本提示', () => {
  assert.match(pageSource, /import \{ notification \} from 'ant-design-vue'/)
  assert.match(pageSource, /showCacheNotification/)
  assert.match(pageSource, /notification\.success/)
  assert.match(pageSource, /notification\.warning/)
  assert.match(pageSource, /notification\.error/)
  assert.doesNotMatch(pageSource, /archive-toast-stack/)
  assert.doesNotMatch(pageSource, /cacheToasts/)
  assert.match(pageSource, /\$\{item\.articleTitle\} 已缓存/)
  assert.match(pageSource, /onBeforeUnmount/)
  assert.match(pageSource, /clearCachePolling/)
})

test('公众号一键缓存完成后展示跳过已有缓存的批次摘要', () => {
  assert.match(pageSource, /job\.skipped/)
  assert.match(pageSource, /showCacheNotification\(job\.message/)
})

test('缓存任务轮询结果同步到顶部状态块并轮播活跃子进程', () => {
  assert.match(pageSource, /cacheJobSnapshot/)
  assert.match(pageSource, /activeProcesses/)
  assert.match(pageSource, /cacheTaskStatusSummary/)
  assert.match(pageSource, /cacheActiveProcessSummary/)
  assert.match(pageSource, /cacheProcessRotationTimer/)
  assert.match(pageSource, /2500/)
  assert.match(pageSource, /cache-process-slide/)
})
