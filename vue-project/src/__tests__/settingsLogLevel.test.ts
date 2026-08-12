import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const currentDir = dirname(fileURLToPath(import.meta.url))
const settingsPageSource = readFileSync(resolve(currentDir, '../pages/SettingsPage.vue'), 'utf8')
const pythonApiSource = readFileSync(resolve(currentDir, '../bridge/pythonApi.ts'), 'utf8')

test('log level is saved and hydrated as backend runtime config', () => {
  assert.match(pythonApiSource, /export type RuntimeLogLevel = 'DEBUG' \| 'INFO' \| 'WARN' \| 'ERROR'/)
  assert.match(pythonApiSource, /logLevel:\s*RuntimeLogLevel/)
  assert.match(settingsPageSource, /logLevel:\s*'INFO'/)
  assert.match(settingsPageSource, /value:\s*'WARN'/)
  assert.match(settingsPageSource, /configForm\.logLevel\s*=\s*status\.config\.logLevel/)
  assert.match(settingsPageSource, /configForm\.requestIntervalSeconds\s*=\s*Math\.round\(status\.config\.requestIntervalSeconds/)
  assert.match(settingsPageSource, /logLevel:\s*configForm\.logLevel/)
  assert.match(settingsPageSource, /requestIntervalSeconds:\s*settingsNumberValues\['basic_settings\.runtime_maintenance\.request_interval_seconds'\]/)
  assert.doesNotMatch(settingsPageSource, /retryCount/)
})
