import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const currentDir = dirname(fileURLToPath(import.meta.url))
const dataFilesPageVue = readFileSync(resolve(currentDir, '../pages/DataFilesPage.vue'), 'utf8')
const appVue = readFileSync(resolve(currentDir, '../App.vue'), 'utf8')
const pythonApiSource = readFileSync(resolve(currentDir, '../bridge/pythonApi.ts'), 'utf8')
const devServerSource = readFileSync(resolve(currentDir, '../../../dev_server.py'), 'utf8')

test('数据档案页顶部卡片复用主服务页右上角数据统计结果', () => {
  assert.match(dataFilesPageVue, /defineProps<\{\s*summaryStats:/)
  assert.match(dataFilesPageVue, /const archiveMetricLabels = new Set\(\['文章数量', '存储占用'\]\)/)
  assert.match(dataFilesPageVue, /props\.summaryStats\.filter\(\(item\) => archiveMetricLabels\.has\(item\.label\)\)/)
  assert.doesNotMatch(dataFilesPageVue, /公众号数量: 'fa-/)
  assert.doesNotMatch(dataFilesPageVue, /运行总时长: 'fa-/)
  assert.doesNotMatch(dataFilesPageVue, /listArchiveSummary/)
  assert.doesNotMatch(dataFilesPageVue, /const archiveSummary = ref/)
  assert.match(appVue, /<DataFilesPage[\s\S]*?:summary-stats="stats"/)
  assert.match(appVue, /buildArchiveSummaryStats\(archiveSummary\.value,\s*formatDuration\(uptimeSeconds\.value\)\)/)
})

test('数据档案页顶部保持四块和固定高度，并增加缓存任务与活跃子进程状态', () => {
  assert.match(dataFilesPageVue, /class="cache-task-status-card/)
  assert.match(dataFilesPageVue, /class="cache-active-process-card/)
  assert.match(dataFilesPageVue, /grid-template-rows: 72px 548px 106px/)
  assert.match(dataFilesPageVue, /缓存任务/)
  assert.match(dataFilesPageVue, /活跃子进程/)
})

test('详情数量字段已从数据档案统计链路删除', () => {
  assert.doesNotMatch(dataFilesPageVue, /详情数量/)
  assert.doesNotMatch(pythonApiSource, /detailCount/)
  assert.doesNotMatch(devServerSource, /detailCount/)
  assert.doesNotMatch(devServerSource, /detail_count/)
})
