import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const currentDir = dirname(fileURLToPath(import.meta.url))
const settingsPageVue = readFileSync(resolve(currentDir, '../pages/SettingsPage.vue'), 'utf8')
const sharedPagesCss = readFileSync(resolve(currentDir, '../styles/pages.css'), 'utf8')

test('指标卡图标支持 red 状态样式', () => {
  assert.doesNotMatch(settingsPageVue, /\.settings-metrics\s+\.metric-icon\.red\s*\{/)
  assert.match(sharedPagesCss, /\.config-summary-metrics\s+\.metric-icon\.red\s*\{/)
  assert.match(sharedPagesCss, /\.metric-icon\.red\s*\{/)
})
