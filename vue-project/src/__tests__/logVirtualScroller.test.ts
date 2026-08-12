import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const currentDir = dirname(fileURLToPath(import.meta.url))
const appVue = readFileSync(resolve(currentDir, '../App.vue'), 'utf8')

test('运行日志使用 vue-virtual-scroller 渲染滚动列表', () => {
  assert.match(appVue, /from 'vue-virtual-scroller'/)
  assert.match(appVue, /<DynamicScroller\b/)
  assert.match(appVue, /<DynamicScrollerItem\b/)
})

test('运行日志滚动区支持用户暂停后自动恢复跟随底部', () => {
  assert.match(appVue, /LOG_AUTO_FOLLOW_IDLE_MS/)
  assert.match(appVue, /@scroll\.passive="handleLogTableScroll"/)
  assert.match(appVue, /@pointerdown\.passive="markLogScrollUserInteraction"/)
  assert.match(appVue, /@wheel\.passive="markLogScrollUserInteraction"/)
  assert.match(appVue, /@keydown="markLogScrollUserInteraction"/)
})

test('运行日志滚动处理使用滚动事件自身的 currentTarget', () => {
  assert.match(appVue, /function handleLogTableScroll\(event: Event\)/)
  assert.match(appVue, /readLogScrollMetricsFromEvent\(event\)/)
  assert.doesNotMatch(appVue, /logTableRef/)
})
