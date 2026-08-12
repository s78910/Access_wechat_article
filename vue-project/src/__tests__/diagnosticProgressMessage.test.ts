import assert from 'node:assert/strict'
import test from 'node:test'

import { resolveDiagnosticProgressMessage } from '../utils/diagnosticProgressMessage.ts'

test('没有已完成步骤时显示正在当前步骤', () => {
  assert.equal(
    resolveDiagnosticProgressMessage({
      status: 'running',
      items: [{ label: '检测 HTML 评论数', value: '执行中' }],
    }),
    '正在检测 HTML 评论数',
  )
})

test('前面有完成步骤时显示上一项完成并正在当前步骤', () => {
  assert.equal(
    resolveDiagnosticProgressMessage({
      status: 'running',
      items: [
        { label: '检测 HTML 评论数', value: '0.008 秒' },
        { label: '提取评论请求参数', value: '执行中' },
      ],
    }),
    '检测 HTML 评论数完成，正在提取评论请求参数',
  )
})

test('后面没有需要做的步骤时显示最后步骤完成', () => {
  assert.equal(
    resolveDiagnosticProgressMessage({
      status: 'completed',
      items: [
        { label: '检测 HTML 评论数', value: '0.008 秒' },
        { label: '提取评论请求参数', value: '0.198 秒' },
        { label: '总耗时', value: '6.178 秒' },
      ],
    }),
    '提取评论请求参数完成',
  )
})
