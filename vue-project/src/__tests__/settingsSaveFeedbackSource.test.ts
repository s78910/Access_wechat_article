import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const settingsPageSource = readFileSync(new URL('../pages/SettingsPage.vue', import.meta.url), 'utf8')

test('保存配置结果统一使用右下角全局提示', () => {
  const saveFunction = settingsPageSource.match(
    /async function handleSaveConfig\(\) \{[\s\S]*?\r?\n\}\r?\n\r?\nasync function handleClearCache/,
  )?.[0]

  assert.ok(saveFunction, '保存配置函数应存在')
  assert.match(saveFunction, /showConfigNotice/)
  assert.doesNotMatch(saveFunction, /showSaveConfigMessage/)
  assert.doesNotMatch(settingsPageSource, /saveConfigMessage/)
  assert.doesNotMatch(settingsPageSource, /save-config-feedback/)
})
