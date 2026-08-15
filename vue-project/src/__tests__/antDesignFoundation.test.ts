import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const packageJson = JSON.parse(
  readFileSync(fileURLToPath(new URL('../../package.json', import.meta.url)), 'utf8'),
) as { dependencies?: Record<string, string> }
const mainSource = readFileSync(fileURLToPath(new URL('../main.ts', import.meta.url)), 'utf8')
const appSource = readFileSync(fileURLToPath(new URL('../App.vue', import.meta.url)), 'utf8')

test('全局接入完整的 Ant Design Vue 组件库', () => {
  assert.ok(packageJson.dependencies?.['ant-design-vue'])
  assert.match(mainSource, /import Antd from 'ant-design-vue'/)
  assert.match(mainSource, /import 'ant-design-vue\/dist\/reset\.css'/)
  assert.match(mainSource, /app\.use\(Antd\)/)
})

test('根页面通过 ConfigProvider 统一中文环境和明暗主题', () => {
  assert.match(appSource, /import zhCN from 'ant-design-vue\/es\/locale\/zh_CN'/)
  assert.match(appSource, /import \{ theme \} from 'ant-design-vue'/)
  assert.match(
    appSource,
    /import type \{ ThemeConfig \} from 'ant-design-vue\/es\/config-provider\/context'/,
  )
  assert.match(appSource, /const antThemeConfig = computed<ThemeConfig>/)
  assert.match(appSource, /isDark\.value \? theme\.darkAlgorithm : theme\.defaultAlgorithm/)
  assert.match(appSource, /<AConfigProvider :locale="zhCN" :theme="antThemeConfig">/)
})

test('日期标签使用 Ant Design Spin 作为首个渐进替换组件', () => {
  const dateLabel = appSource.match(
    /<span class="task-control-label task-date-label download-option selected locked">[\s\S]*?<\/span>/,
  )
  assert.ok(dateLabel)
  assert.match(dateLabel[0], /<ASpin/)
  assert.match(dateLabel[0], /class="task-date-label-spin"/)
  assert.match(dateLabel[0], /size="small"/)
  assert.match(dateLabel[0], /:spinning="true"/)
})

test('Ant Design 日期组件统一使用 Day.js 中文语言环境', () => {
  assert.ok(packageJson.dependencies?.dayjs)
  assert.match(mainSource, /import dayjs from 'dayjs'/)
  assert.match(mainSource, /import 'dayjs\/locale\/zh-cn'/)
  assert.match(mainSource, /dayjs\.locale\('zh-cn'\)/)
})
