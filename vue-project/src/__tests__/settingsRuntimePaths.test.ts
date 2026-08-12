import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const currentDir = dirname(fileURLToPath(import.meta.url))
const settingsPageSource = readFileSync(resolve(currentDir, '../pages/SettingsPage.vue'), 'utf8')
const pythonApiSource = readFileSync(resolve(currentDir, '../bridge/pythonApi.ts'), 'utf8')

test('基础设置目录从后端实际运行路径读取，不再保留旧 Pre-release 静态路径', () => {
  assert.match(settingsPageSource, /listRuntimePaths/)
  assert.match(settingsPageSource, /hydrateRuntimePaths/)
  assert.doesNotMatch(settingsPageSource, /Github-240809_wechat_article\\\\Pre-release/)
})

test('基础设置浏览按钮按目录 key 调用后端打开对应文件夹', () => {
  assert.match(settingsPageSource, /openRuntimePath/)
  for (const key of ['projectDir', 'storageDir', 'logDir']) {
    assert.match(settingsPageSource, new RegExp(`handleOpenRuntimePath\\('${key}'\\)`))
  }
  assert.doesNotMatch(settingsPageSource, /handleOpenRuntimePath\('outputDir'\)/)
  assert.doesNotMatch(settingsPageSource, /for="output-dir"/)
  assert.doesNotMatch(settingsPageSource, /id="output-dir"/)
  assert.doesNotMatch(settingsPageSource, /configForm\.outputDir/)
  assert.doesNotMatch(settingsPageSource, /运行输出目录/)
})

test('three-pane settings center sits above the bottom environment and action panels', () => {
  assert.match(settingsPageSource, /\.settings-page\s*\{[^}]*grid-template-rows:\s*minmax\(0,\s*1fr\)\s+216px/s)
  assert.doesNotMatch(settingsPageSource, /\.settings-page\s*\{[^}]*grid-template-rows:\s*70px/s)
  assert.doesNotMatch(settingsPageSource, /\.settings-page\s*\{[^}]*'metrics metrics metrics metrics metrics metrics'/s)
  assert.match(settingsPageSource, /\.settings-page\s*\{[^}]*'center center center center center center'/s)
  assert.match(settingsPageSource, /\.settings-page\s*\{[^}]*'bottom bottom bottom bottom bottom bottom'/s)
  assert.match(settingsPageSource, /\.settings-three-pane\s*\{[^}]*grid-area:\s*center/s)
  assert.match(settingsPageSource, /\.settings-three-pane\s*\{[^}]*grid-template-columns:\s*230px\s+300px\s+minmax\(0,\s*1fr\)/s)
  assert.match(settingsPageSource, /\.settings-bottom-panels\s*\{[^}]*grid-area:\s*bottom/s)
  assert.match(settingsPageSource, /\.settings-bottom-panels\s*\{[^}]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)/s)
})

test('前端桥接层提供运行目录读取和打开目录接口', () => {
  assert.match(pythonApiSource, /export async function listRuntimePaths/)
  assert.match(pythonApiSource, /'\/api\/runtime\/paths'/)
  assert.match(pythonApiSource, /export async function openRuntimePath/)
  assert.match(pythonApiSource, /'\/api\/runtime\/paths\/open'/)
})

test('前端桥接层不再保留未使用的旧桌面桥接和 CA 安装页入口', () => {
  assert.doesNotMatch(pythonApiSource, /resizeWindowToContent/)
  assert.doesNotMatch(pythonApiSource, /resize_window_to_content/)
  assert.doesNotMatch(pythonApiSource, /openCaInstallPage/)
  assert.doesNotMatch(pythonApiSource, /open_ca_install_page/)
  assert.doesNotMatch(pythonApiSource, /\/api\/ca\/install\/open/)
})

test('file name mode dropdown only exposes the active archive naming rule', () => {
  const optionsBlock = settingsPageSource.match(/const fileNameModeOptions = \[[\s\S]*?\]\r?\n/)
  assert.ok(optionsBlock)
  assert.match(optionsBlock[0], /CONFIG\.fileNameMode/)
  assert.doesNotMatch(optionsBlock[0], /fileNameTitleMode/)
  assert.doesNotMatch(settingsPageSource, /fileNameTitleMode/)
  assert.match(settingsPageSource, /YYYY-MM-DD HH-mm TITLE/)
})
