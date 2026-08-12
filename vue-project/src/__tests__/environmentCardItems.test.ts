import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const currentDir = dirname(fileURLToPath(import.meta.url))
const appVue = readFileSync(resolve(currentDir, '../App.vue'), 'utf8')

test('运行环境卡展示 Playwright 实际版本字段', () => {
  assert.match(appVue, /name:\s*'Playwright'/)
  assert.match(appVue, /environmentStatus\.value\.playwrightVersion/)
})
