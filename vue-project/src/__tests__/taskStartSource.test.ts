import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const appVue = readFileSync(new URL('../App.vue', import.meta.url), 'utf-8')

test('主服务开始和停止按钮暂不绑定任务启动停止逻辑', () => {
  assert.match(appVue, /<span class="button-label">开始运行<\/span>/)
  assert.match(appVue, /<span class="button-label">停止<\/span>/)
  assert.doesNotMatch(appVue, /@click="handleStartTask"/)
  assert.doesNotMatch(appVue, /@click="handleStopTask"/)
  assert.doesNotMatch(appVue, /async function handleStartTask\(/)
  assert.doesNotMatch(appVue, /async function handleStopTask\(/)
  assert.doesNotMatch(appVue, /await startTask\(/)
  assert.doesNotMatch(appVue, /await stopTask\(/)
})
