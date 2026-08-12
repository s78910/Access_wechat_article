import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const currentDir = dirname(fileURLToPath(import.meta.url))
const appVue = readFileSync(resolve(currentDir, '../App.vue'), 'utf8')
const trafficSparkline = readFileSync(resolve(currentDir, '../components/TrafficSparkline.vue'), 'utf8')

function getStyleBlock(source: string, selectorPattern: RegExp) {
  const match = source.match(selectorPattern)
  assert.ok(match?.groups?.body, `missing style block: ${selectorPattern}`)
  return match.groups.body
}

test('traffic speed labels use the same colors as the sparkline lanes', () => {
  assert.match(appVue, /<strong\s+class="speed-upload">↑ \{\{\s*trafficUploadLabel\s*\}\}<\/strong>/)
  assert.match(appVue, /<strong\s+class="speed-download">↓ \{\{\s*trafficDownloadLabel\s*\}\}<\/strong>/)

  const uploadLineBlock = getStyleBlock(trafficSparkline, /\.traffic-line\.upload\s*\{(?<body>[\s\S]*?)\}/)
  const downloadLineBlock = getStyleBlock(trafficSparkline, /\.traffic-line\.download\s*\{(?<body>[\s\S]*?)\}/)
  const uploadSpeedBlock = getStyleBlock(appVue, /\.speed-upload\s*\{(?<body>[\s\S]*?)\}/)
  const downloadSpeedBlock = getStyleBlock(appVue, /\.speed-download\s*\{(?<body>[\s\S]*?)\}/)

  assert.match(uploadLineBlock, /stroke:\s*var\(--green\);/)
  assert.match(downloadLineBlock, /stroke:\s*var\(--blue\);/)
  assert.match(uploadSpeedBlock, /color:\s*var\(--green\);/)
  assert.match(downloadSpeedBlock, /color:\s*var\(--blue\);/)
})
