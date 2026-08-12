import assert from 'node:assert/strict'
import test from 'node:test'

import { resolveTaskProgressSummary } from '../utils/taskProgress.ts'

test('任务完成后从汇总日志中解析完成数量、失败数量和进度', () => {
  const summary = resolveTaskProgressSummary({
    plannedCount: 1,
    logs: [
      {
        level: 'SUCCESS',
        message: '文章抓取任务已完成，本次保存 1/1 篇，失败 0 篇',
        source: 'article_capture',
        createdAt: '2026-06-20T13:03:27',
      },
    ],
  })

  assert.equal(summary.completedCount, 1)
  assert.equal(summary.failedCount, 0)
  assert.equal(summary.totalLabel, '1')
  assert.equal(summary.progressPercent, 100)
})

test('任务运行中优先使用进度事件中的 progress 字段', () => {
  const summary = resolveTaskProgressSummary({
    plannedCount: 3,
    logs: [
      {
        level: 'INFO',
        message: '步骤[mitm] 开始等待 MITM 捕获文章主 HTML，最长等待 10 秒',
        source: 'article_capture',
        createdAt: '2026-06-20T13:03:14',
        progress: 25,
      },
      {
        level: 'SUCCESS',
        message: '主页第 1 篇文章已保存：测试文章',
        source: 'article_capture',
        createdAt: '2026-06-20T13:03:27',
      },
    ],
  })

  assert.equal(summary.completedCount, 1)
  assert.equal(summary.failedCount, 0)
  assert.equal(summary.totalLabel, '3')
  assert.equal(summary.progressPercent, 25)
})

test('没有日志时保持零进度并显示全部任务标签', () => {
  const summary = resolveTaskProgressSummary({
    plannedCount: 0,
    logs: [],
  })

  assert.equal(summary.completedCount, 0)
  assert.equal(summary.failedCount, 0)
  assert.equal(summary.totalLabel, '全部')
  assert.equal(summary.progressPercent, 0)
})
