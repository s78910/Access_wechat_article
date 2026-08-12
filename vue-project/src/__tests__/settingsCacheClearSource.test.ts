import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const settingsPageSource = readFileSync(new URL('../pages/SettingsPage.vue', import.meta.url), 'utf8')

test('清理运行缓存不删除浏览器持久化配置', () => {
  assert.doesNotMatch(settingsPageSource, /localStorage\.clear\(\)/)
  assert.doesNotMatch(settingsPageSource, /sessionStorage\.clear\(\)/)
  assert.match(settingsPageSource, /caches\.keys\(\)/)
})

test('采集或诊断运行时禁用清理缓存按钮', () => {
  assert.match(settingsPageSource, /const isRuntimeCacheBusy = computed/)
  assert.match(settingsPageSource, /isWindowClickFlowDiagnosticRunning\.value/)
  assert.match(settingsPageSource, /isArticleDetailDiagnosticRunning\.value/)
  assert.match(settingsPageSource, /:disabled="isClearingCache \|\| isRuntimeCacheBusy"/)
})
