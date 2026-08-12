import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const appVue = readFileSync(new URL('../App.vue', import.meta.url), 'utf-8')
const settingsPageVue = readFileSync(new URL('../pages/SettingsPage.vue', import.meta.url), 'utf-8')

test('系统配置页接收 App 层实时 TaskStatus，避免与主服务页状态脱节', () => {
  assert.match(appVue, /<SettingsPage[\s\S]*:task-status="taskStatus"/)
  assert.match(settingsPageVue, /taskStatus\?: TaskStatus \| null/)
  assert.match(settingsPageVue, /props\.taskStatus \?\? runtimeStatus\.value/)
  assert.doesNotMatch(settingsPageVue, /buildSettingsRuntimeMetrics/)
  assert.doesNotMatch(settingsPageVue, /settingsMetrics/)
})

test('系统配置页运行环境复用 App 层环境状态，避免读取静态 mock 数据', () => {
  assert.match(appVue, /<SettingsPage[\s\S]*:environment-items="envItems"/)
  assert.match(settingsPageVue, /environmentItems\?: EnvironmentItem\[\]/)
  assert.match(settingsPageVue, /props\.environmentItems \?\? \[\]/)
  assert.doesNotMatch(settingsPageVue, /buildSettingsEnvironmentItems/)
  assert.doesNotMatch(settingsPageVue, /environmentStatus\?: EnvironmentStatus \| null/)
  assert.doesNotMatch(settingsPageVue, /import\s+\{\s*environmentItems\s*\}\s+from\s+'..\/data\/mockData'/)
  assert.doesNotMatch(settingsPageVue, />\s*可采集\s*</)
})
