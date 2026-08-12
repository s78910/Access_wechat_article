import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const currentDir = dirname(fileURLToPath(import.meta.url))
const pageSource = readFileSync(resolve(currentDir, '../pages/HistoryPage.vue'), 'utf8')
const apiSource = readFileSync(resolve(currentDir, '../bridge/pythonApi.ts'), 'utf8')

test('采集历史状态筛选使用数据库允许的 success 和 failed', () => {
  assert.match(pageSource, /label:\s*'成功',\s*value:\s*'success'/)
  assert.match(pageSource, /label:\s*'失败',\s*value:\s*'failed'/)
  assert.doesNotMatch(pageSource, /label:\s*'成功',\s*value:\s*'saved'/)
})

test('顶部指标绑定历史任务、成功率、yyyy-mm-dd 最近日期和去重文章数', () => {
  assert.match(pageSource, /label:\s*'历史任务数'[\s\S]*summary\?\.totalRecords/)
  assert.match(pageSource, /label:\s*'成功率'[\s\S]*summary\?\.successRate/)
  assert.match(pageSource, /label:\s*'最近采集日期'[\s\S]*summary\?\.latestCollectDate/)
  assert.match(pageSource, /label:\s*'累计采集文章'[\s\S]*summary\?\.collectedArticleCount/)
  assert.doesNotMatch(
    pageSource,
    /label:\s*'累计采集文章'[\s\S]*value:\s*String\(summary\?\.totalRecords/,
  )
  assert.match(apiSource, /latestCollectDate:\s*string/)
  assert.match(apiSource, /collectedArticleCount:\s*number/)
})

test('记录详情展示开始结束时间、文章发布时间、资源产物和失败信息', () => {
  for (const field of [
    'startedTime',
    'finishedTime',
    'publishedArticleTime',
    'articleLink',
    'resourceTypeLabels',
    'outputDir',
    'errorStageLabel',
    'errorMessage',
  ]) {
    assert.match(apiSource, new RegExp(`${field}:\\s*`), `${field} should be declared in HistoryRecordItem`)
    assert.match(pageSource, new RegExp(`record\\.${field}`), `${field} should be bound into recordDetail`)
  }

  assert.match(pageSource, /<span>文章发布时间<\/span>/)
  assert.match(pageSource, /<span>开始时间<\/span>/)
  assert.match(pageSource, /<span>结束时间<\/span>/)
  assert.match(pageSource, /<span>资源类型<\/span>/)
  assert.match(pageSource, /<span>输出目录<\/span>/)
  assert.match(pageSource, /<span>失败阶段<\/span>/)
  assert.match(pageSource, /<span>失败原因<\/span>/)
})

test('关键词查询使用 250ms 防抖并忽略过期响应', () => {
  assert.match(pageSource, /const HISTORY_QUERY_DEBOUNCE_MS = 250/)
  assert.match(pageSource, /let historyRecordsRequestId = 0/)
  assert.match(pageSource, /let historySuggestionsRequestId = 0/)
  assert.match(pageSource, /const requestId = \+\+historyRecordsRequestId/)
  assert.match(pageSource, /requestId !== historyRecordsRequestId/)
  assert.match(pageSource, /const requestId = \+\+historySuggestionsRequestId/)
  assert.match(pageSource, /requestId !== historySuggestionsRequestId/)
  assert.match(pageSource, /setTimeout\([\s\S]*HISTORY_QUERY_DEBOUNCE_MS/)
})

test('统计加载失败被单独捕获，不中断列表和候选加载', () => {
  const summaryFunction = pageSource.match(
    /async function loadHistorySummary\(\)[\s\S]*?\n\}\n\nasync function loadHistorySuggestions/,
  )

  assert.ok(summaryFunction)
  assert.match(summaryFunction[0], /catch\s*\(/)
})
