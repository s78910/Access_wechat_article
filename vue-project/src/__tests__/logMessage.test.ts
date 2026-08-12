import assert from 'node:assert/strict'
import test from 'node:test'

import { formatLogMessageSegments } from '../utils/logMessage.ts'

test('长 URL 日志拆成前缀文本和可单行省略的 URL 片段', () => {
  const message = '已捕获文章主请求 URL：https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn&key=secret'

  const segments = formatLogMessageSegments(message)

  assert.deepEqual(segments, [
    { type: 'text', text: '已捕获文章主请求 URL：' },
    {
      type: 'url',
      text: 'https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn&key=secret',
      fullText: 'https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=sn&key=secret',
    },
  ])
})

test('URL 位于日志开头时也作为 URL 片段处理', () => {
  const segments = formatLogMessageSegments('https://mp.weixin.qq.com/s/abc')

  assert.deepEqual(segments, [
    { type: 'text', text: '' },
    { type: 'url', text: 'https://mp.weixin.qq.com/s/abc', fullText: 'https://mp.weixin.qq.com/s/abc' },
  ])
})
