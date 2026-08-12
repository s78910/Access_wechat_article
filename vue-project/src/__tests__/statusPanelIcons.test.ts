import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const currentDir = dirname(fileURLToPath(import.meta.url))
const appVue = readFileSync(resolve(currentDir, '../App.vue'), 'utf8')
const iconRegistrySource = readFileSync(resolve(currentDir, '../icons/fontAwesomeIcons.ts'), 'utf8')

test('程序运行状态中当前动作使用执行动作图标', () => {
  assert.match(appVue, /label: '当前动作'[\s\S]*?icon: 'fa-solid fa-bolt'/)
  assert.match(iconRegistrySource, /'fa-solid fa-bolt':/)
})

test('程序运行状态中代理状态使用网络代理图标', () => {
  assert.match(appVue, /label: '代理状态'[\s\S]*?icon: 'fa-solid fa-network-wired'/)
  assert.match(iconRegistrySource, /'fa-solid fa-network-wired':/)
})
