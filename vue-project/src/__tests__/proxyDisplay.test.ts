import assert from 'node:assert/strict'
import test from 'node:test'

import {
  resolveProxyConnectionLabel,
  resolveProxyConfiguredServer,
  resolveProxyDisplayStatus,
} from '../utils/proxyDisplay.ts'

test('proxy display shows takeover only from actual backend proxy fields', () => {
  const status = resolveProxyDisplayStatus('idle', {
    host: '127.0.0.1',
    port: 18000,
    enabled: true,
    mitmEnabled: true,
    systemProxyActive: true,
    systemProxyReadable: true,
    systemProxyServer: '127.0.0.1:18000',
    configuredProxyServer: '127.0.0.1:18000',
  })

  assert.equal(status.label, '已接管 127.0.0.1:18000')
  assert.equal(status.tone, 'green')
})

test('proxy display does not synthesize takeover from placeholder host and port', () => {
  const status = resolveProxyDisplayStatus('idle', {
    host: '127.0.0.1',
    port: 18000,
    enabled: true,
    mitmEnabled: true,
    systemProxyActive: true,
  })

  assert.equal(status.label, '系统代理状态未知')
  assert.equal(status.tone, 'orange')
  assert.doesNotMatch(status.label, /127\.0\.0\.1:18000/)
})

test('topbar configured proxy server does not fallback to placeholder host and port', () => {
  assert.equal(resolveProxyConfiguredServer({
    host: '127.0.0.1',
    port: 18000,
    enabled: true,
    mitmEnabled: true,
  }), '')
})

test('proxy display hides listener address when MITM proxy is not running', () => {
  const status = resolveProxyDisplayStatus('idle', {
    host: '127.0.0.1',
    port: 18000,
    enabled: false,
    mitmEnabled: false,
    systemProxyReadable: true,
    systemProxyActive: false,
    systemProxyServer: '127.0.0.1:18000',
    configuredProxyServer: '127.0.0.1:18000',
  })

  assert.equal(status.label, 'MITM 未开启')
  assert.equal(status.tone, 'orange')
  assert.doesNotMatch(status.label, /127\.0\.0\.1:18000/)
})

test('proxy display warns without address when system proxy remains enabled but MITM is stopped', () => {
  const status = resolveProxyDisplayStatus('idle', {
    host: '127.0.0.1',
    port: 18000,
    enabled: false,
    mitmEnabled: false,
    systemProxyReadable: true,
    systemProxyActive: true,
    systemProxyServer: '127.0.0.1:18000',
    configuredProxyServer: '127.0.0.1:18000',
  })

  assert.equal(status.label, '系统代理已开启，MITM 未开启')
  assert.equal(status.tone, 'red')
  assert.doesNotMatch(status.label, /127\.0\.0\.1:18000/)
})

test('topbar connection label hides configured address when MITM is not connected', () => {
  const label = resolveProxyConnectionLabel(false, {
    configuredProxyServer: '127.0.0.1:18000',
  })

  assert.equal(label, '未连接')
  assert.doesNotMatch(label, /127\.0\.0\.1:18000/)
})
