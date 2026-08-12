import assert from 'node:assert/strict'
import test from 'node:test'

import {
  canResumeLogAutoFollow,
  isLogScrollNearBottom,
  LOG_AUTO_FOLLOW_IDLE_MS,
  readLogScrollMetricsFromEvent,
} from '../utils/logScroll.ts'

test('日志距离底部 24px 内时允许自动贴底', () => {
  assert.equal(isLogScrollNearBottom({
    scrollHeight: 1000,
    scrollTop: 776,
    clientHeight: 200,
  }), true)
})

test('用户向上查看历史日志时暂停自动贴底', () => {
  assert.equal(isLogScrollNearBottom({
    scrollHeight: 1000,
    scrollTop: 740,
    clientHeight: 200,
  }), false)
})

test('用户停止操作 10 秒后恢复自动跟随最新日志', () => {
  assert.equal(canResumeLogAutoFollow(1000, 1000 + LOG_AUTO_FOLLOW_IDLE_MS - 1), false)
  assert.equal(canResumeLogAutoFollow(1000, 1000 + LOG_AUTO_FOLLOW_IDLE_MS), true)
})

test('日志滚动事件从 currentTarget 读取真实滚动容器位置', () => {
  const currentTarget = {
    scrollHeight: 1000,
    scrollTop: 740,
    clientHeight: 200,
  }

  const metrics = readLogScrollMetricsFromEvent({ currentTarget } as unknown as Event)

  assert.deepEqual(metrics, currentTarget)
  assert.equal(isLogScrollNearBottom(metrics!), false)
})
