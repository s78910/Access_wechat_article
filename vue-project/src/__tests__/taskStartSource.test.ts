import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const appVue = readFileSync(new URL('../App.vue', import.meta.url), 'utf-8')

test('点击开始运行后立即进入 starting 状态，让停止按钮无需等待后端响应即可可用', () => {
  assert.match(appVue, /function markTaskStarting\(\)/)
  assert.match(appVue, /async function handleStartTask\(\)[\s\S]*markTaskStarting\(\)[\s\S]*await startTask/)
})
