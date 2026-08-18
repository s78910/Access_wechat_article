import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const appSource = readFileSync(new URL('../App.vue', import.meta.url), 'utf8')
const settingsPageSource = readFileSync(new URL('../pages/SettingsPage.vue', import.meta.url), 'utf8')

function requireSourceBlock(source: string, pattern: RegExp, label: string) {
  const match = source.match(pattern)

  assert.ok(match, `${label} 应存在`)
  return match[0]
}

test('进入系统配置页面时只加载状态，不自动执行 CA 证书诊断', () => {
  const mountedBlock = requireSourceBlock(
    settingsPageSource,
    /onMounted\(\(\) => \{[\s\S]*?\n\}\)/,
    '系统配置页 onMounted',
  )

  assert.doesNotMatch(mountedBlock, /handleCheckCaCertificate\(\)/)
})

test('MITM 运行状态同步不通过 watch 自动调用启停接口', () => {
  assert.doesNotMatch(settingsPageSource, /watch\(\s*\(\) => settings\.autoStartProxy/)
})

test('系统代理配置开关只同步内存配置，不直接修改 Windows 系统代理', () => {
  const watcherBlock = requireSourceBlock(
    settingsPageSource,
    /watch\(\s*\(\) => settings\.enableSystemProxy,[\s\S]*?\n\)/,
    '系统代理配置 watch',
  )

  assert.match(watcherBlock, /handleConfigFieldNotice/)
  assert.doesNotMatch(watcherBlock, /await enableSystemProxy\(\)|await disableSystemProxy\(\)/)
})

test('实际代理状态同步不覆盖系统代理接管配置', () => {
  const snapshotBlock = requireSourceBlock(
    settingsPageSource,
    /function applyProxyStatusSnapshot\(status: TaskStatus \| null \| undefined\)[\s\S]*?\n\}/,
    '代理状态同步函数',
  )

  assert.doesNotMatch(snapshotBlock, /settings\.enableSystemProxy\s*=/)
})

test('任务状态和日志只在任务启动中或运行中轮询', () => {
  const mountedBlock = requireSourceBlock(appSource, /onMounted\((?:async )?\(\) => \{[\s\S]*?\n\}\)/, 'App onMounted')
  const refreshBlock = requireSourceBlock(
    appSource,
    /async function refreshTaskRuntime\(\) \{[\s\S]*?\n\}/,
    '任务状态刷新函数',
  )

  assert.match(appSource, /function shouldPollTaskRuntime\(status: TaskStatus\)/)
  assert.match(appSource, /status\.status === 'starting' \|\| status\.status === 'running'/)
  assert.match(refreshBlock, /syncTaskPolling\(status\)/)
  assert.doesNotMatch(mountedBlock, /startTaskPolling\(\)/)
})

test('诊断接口的托管状态不会停止正在运行的任务轮询', () => {
  assert.match(appSource, /function isTaskLifecycleStatus\(status: TaskStatus\)/)
  assert.match(appSource, /\['idle', 'starting', 'running', 'stopped', 'error'\]/)
  assert.match(appSource, /if \(!isTaskLifecycleStatus\(status\)\) \{\s*return\s*\}/)
})
