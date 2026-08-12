import assert from 'node:assert/strict'
import test from 'node:test'

import {
  getBrowserPreviewEnvironmentStatus,
  getEnvironmentErrorStatus,
  INITIAL_ENVIRONMENT_STATUS,
  resolvePywebviewEnvironmentStatus,
} from '../utils/pywebviewStatus.ts'

test('pywebview 桥接未注入时保持检测中并请求重试', () => {
  const result = resolvePywebviewEnvironmentStatus({
    ok: false,
    status: 'browser-preview',
  })

  assert.equal(result.shouldRetry, true)
  assert.equal(result.pywebviewStatusLabel, '检测中')
  assert.deepEqual(result.environmentStatus, INITIAL_ENVIRONMENT_STATUS)
})

test('pywebview 已连接时映射真实运行环境信息', () => {
  const result = resolvePywebviewEnvironmentStatus({
    ok: true,
    status: 'ready',
    environment: {
      systemLabel: 'Windows 11 x64',
      appVersion: '2.0.0',
      pythonVersion: '3.13.5',
      mitmproxyVersion: '10.2.0',
      playwrightVersion: '1.57.0',
      pywebviewVersion: '5.4',
    },
  })

  assert.equal(result.shouldRetry, false)
  assert.equal(result.pywebviewStatusLabel, '已连接')
  assert.deepEqual(result.environmentStatus, {
    systemLabel: 'Windows 11 x64',
    appVersion: '2.0.0',
    pythonVersion: '3.13.5',
    mitmproxyVersion: '10.2.0',
    playwrightVersion: '1.57.0',
    pywebviewVersion: '5.4',
  })
})

test('重试耗尽后显示浏览器预览，异常时显示读取失败', () => {
  const browserPreview = getBrowserPreviewEnvironmentStatus()
  const failed = getEnvironmentErrorStatus()

  assert.equal(browserPreview.shouldRetry, false)
  assert.equal(browserPreview.pywebviewStatusLabel, '浏览器预览')
  assert.equal(browserPreview.environmentStatus.pywebviewVersion, '浏览器预览')

  assert.equal(failed.shouldRetry, false)
  assert.equal(failed.pywebviewStatusLabel, '连接失败')
  assert.equal(failed.environmentStatus.pythonVersion, '读取失败')
  assert.equal(failed.environmentStatus.playwrightVersion, '读取失败')
})
