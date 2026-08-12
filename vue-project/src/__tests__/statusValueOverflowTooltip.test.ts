import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const currentDir = dirname(fileURLToPath(import.meta.url))
const appVue = readFileSync(resolve(currentDir, '../App.vue'), 'utf8')

test('status value tooltip is shown only when the value text overflows', () => {
  const overflowFunction = appVue.match(/function\s+isStatusValueOverflowing[\s\S]*?\n\}/)
  const tooltipFunction = appVue.match(/function\s+showStatusValueTooltip[\s\S]*?\n\}/)

  assert.ok(overflowFunction?.[0], 'missing overflow detection function')
  assert.ok(tooltipFunction?.[0], 'missing status tooltip function')
  assert.match(overflowFunction[0], /scrollWidth\s*>\s*target\.clientWidth/)
  assert.match(tooltipFunction[0], /isStatusValueOverflowing\(event\)/)
})

test('normal status values share the single-line ellipsis tooltip behavior', () => {
  const normalValueMatch = appVue.match(/<strong\s+v-else\s+:class="\[(?<classBinding>[\s\S]*?)\]"(?<body>[\s\S]*?)>\s*\{\{\s*item\.value\s*\}\}\s*<\/strong>/)

  assert.ok(normalValueMatch?.groups?.classBinding, 'normal status value should use a bound class list')
  assert.match(normalValueMatch.groups.classBinding, /status-value/)
  assert.match(normalValueMatch.groups.classBinding, /status-value-ellipsis/)
  assert.match(normalValueMatch.groups.body, /@mouseenter="showStatusValueTooltip\(\$event,\s*item\.value\)"/)
  assert.doesNotMatch(appVue, /v-else-if="item\.label === '公众号简介'"/)
})
