import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const currentDir = dirname(fileURLToPath(import.meta.url))
const appVue = readFileSync(resolve(currentDir, '../App.vue'), 'utf8')

function getStyleBlock(selectorPattern: RegExp) {
  const match = appVue.match(selectorPattern)
  assert.ok(match?.groups?.body, `missing style block: ${selectorPattern}`)
  return match.groups.body
}

test('task control buttons disable pointer interaction and look inactive', () => {
  const disabledBlock = getStyleBlock(/\.run-button:disabled,\s*\.stop-button:disabled\s*\{(?<body>[\s\S]*?)\}/)

  assert.match(disabledBlock, /cursor:\s*not-allowed;/)
  assert.match(disabledBlock, /pointer-events:\s*none;/)
  assert.match(disabledBlock, /opacity:\s*0\.[0-9]+;/)
  assert.match(disabledBlock, /filter:\s*grayscale\([^)]+\)\s*saturate\([^)]+\);/)
  assert.match(disabledBlock, /box-shadow:/)
})

test('disabled task control buttons do not receive hover or active lift', () => {
  const lockedInteractionBlock = getStyleBlock(
    /\.run-button:disabled:hover,\s*\.stop-button:disabled:hover,\s*\.run-button:disabled:active,\s*\.stop-button:disabled:active\s*\{(?<body>[\s\S]*?)\}/,
  )

  assert.match(lockedInteractionBlock, /transform:\s*none;/)
  assert.match(lockedInteractionBlock, /box-shadow:/)
})
