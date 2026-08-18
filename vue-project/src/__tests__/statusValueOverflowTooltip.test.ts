import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const currentDir = dirname(fileURLToPath(import.meta.url))
const appVue = readFileSync(resolve(currentDir, '../App.vue'), 'utf8')

test('status value tooltip uses Ant Design Tooltip only when the value text overflows', () => {
  const overflowFunction = appVue.match(/function\s+isStatusValueOverflowing[\s\S]*?\n\}/)
  const tooltipFunction = appVue.match(/function\s+prepareStatusValueTooltip[\s\S]*?\n\}/)

  assert.ok(overflowFunction?.[0], 'missing overflow detection function')
  assert.ok(tooltipFunction?.[0], 'missing status tooltip function')
  assert.match(overflowFunction[0], /scrollWidth\s*>\s*target\.clientWidth/)
  assert.match(tooltipFunction[0], /isStatusValueOverflowing\(event\)/)
  assert.match(tooltipFunction[0], /statusValueTooltipKey\.value\s*=\s*isStatusValueOverflowing\(event\)\s*\?\s*key\s*:\s*''/)
  assert.doesNotMatch(appVue, /class="description-tooltip"/)
})

test('normal status values share the single-line ellipsis Ant Tooltip behavior', () => {
  const tooltipMatch = appVue.match(/<ATooltip\s+v-else(?<tooltipAttrs>[\s\S]*?)>\s*<strong\s+:class="\[(?<classBinding>[\s\S]*?)\]"(?<body>[\s\S]*?)>\s*\{\{\s*item\.value\s*\}\}\s*<\/strong>\s*<\/ATooltip>/)

  assert.ok(tooltipMatch?.groups?.classBinding, 'normal status value should be wrapped by Ant Design Tooltip')
  assert.match(tooltipMatch.groups.tooltipAttrs, /:title="item\.value"/)
  assert.match(tooltipMatch.groups.tooltipAttrs, /:open="statusValueTooltipKey === item\.label"/)
  assert.match(tooltipMatch.groups.classBinding, /status-value/)
  assert.match(tooltipMatch.groups.classBinding, /status-value-ellipsis/)
  assert.match(tooltipMatch.groups.body, /@mouseenter="prepareStatusValueTooltip\(\$event,\s*item\.label\)"/)
  assert.doesNotMatch(appVue, /v-else-if="item\.label === '公众号简介'"/)
})
