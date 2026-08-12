import assert from 'node:assert/strict'
import test from 'node:test'

import { buildSettingsRuntimeMetrics } from '../utils/settingsRuntimeMetrics.ts'


test('system settings app version reuses environment status', () => {
  const metrics = buildSettingsRuntimeMetrics(
    {
      ok: true,
      status: 'idle',
    },
    {
      appVersion: '3.1.4',
    },
  )

  assert.equal(metrics[0].label, '应用版本')
  assert.equal(metrics[0].value, '3.1.4')
  assert.equal(metrics[0].tone, 'blue')
})

test('系统配置状态卡复用主服务运行状态、窗口状态和 MITM 鉴权状态', () => {
  const metrics = buildSettingsRuntimeMetrics(
    {
      ok: true,
      status: 'running',
      home: {
        status: 'ready',
        statusLabel: '主页信息已获取',
        accountName: '新华社',
        description: '国家通讯社',
        originalCount: '120',
        friendFollowCount: '34',
        found: true,
      },
      auth: {
        hasKeyUrl: true,
        status: 'captured',
        statusLabel: '已获取鉴权',
        lastKeyUrlAt: '2026-06-21T15:30:00',
        lastKeyUrlSource: 'request',
      },
      proxy: {
        host: '127.0.0.1',
        port: 18000,
        enabled: true,
        mitmEnabled: true,
      },
    },
    {
      appVersion: '2.0.0',
    },
  )

  assert.deepEqual(
    metrics.map((item) => [item.label, item.value, item.tone]),
    [
      ['应用版本', '2.0.0', 'blue'],
      ['程序状态', '采集中', 'green'],
      ['窗口检测', '主页信息已获取', 'green'],
      ['鉴权状态', '已获取鉴权', 'green'],
    ],
  )
  assert.equal(metrics[2].hint, '新华社')
  assert.equal(metrics[3].hint, '已捕获带 key 的文章 URL')
})

test('MITM 运行但未捕获 key URL 时，鉴权状态显示等待鉴权', () => {
  const metrics = buildSettingsRuntimeMetrics(
    {
      ok: true,
      status: 'idle',
      home: {
        status: 'not_found',
        statusLabel: '未检测到主页窗口',
        accountName: '未检测到微信 PC 公众号主页',
        description: '',
        originalCount: '',
        friendFollowCount: '',
        found: false,
      },
      auth: {
        hasKeyUrl: false,
        status: 'waiting',
        statusLabel: '等待鉴权',
      },
      proxy: {
        host: '127.0.0.1',
        port: 18000,
        enabled: false,
        mitmEnabled: true,
      },
    },
    {
      appVersion: '2.0.0',
    },
  )

  assert.deepEqual(
    metrics.map((item) => [item.label, item.value, item.tone]),
    [
      ['应用版本', '2.0.0', 'blue'],
      ['程序状态', '待机', 'orange'],
      ['窗口检测', '未检测到主页窗口', 'red'],
      ['鉴权状态', '等待鉴权', 'orange'],
    ],
  )
})

test('窗口检测状态卡使用稳定的桌面图标', () => {
  const statuses = [
    { status: 'ready', found: true },
    { status: 'display_cached', found: false },
    { status: 'not_found', found: false },
    { status: '', found: false },
  ]

  for (const item of statuses) {
    const metrics = buildSettingsRuntimeMetrics({
      home: {
        status: item.status,
        statusLabel: item.status || '检测中',
        accountName: '',
        description: '',
        originalCount: '',
        friendFollowCount: '',
        found: item.found,
      },
    })

    assert.equal(metrics[2].icon, 'fa-solid fa-desktop')
  }
})

test('MITM 未运行时，鉴权状态显示未启动代理', () => {
  const metrics = buildSettingsRuntimeMetrics({
    ok: true,
    status: 'stopped',
    auth: {
      hasKeyUrl: false,
      status: 'not_started',
      statusLabel: '未启动代理',
    },
    proxy: {
      host: '127.0.0.1',
      port: 18000,
      enabled: false,
      mitmEnabled: false,
    },
  })

  assert.deepEqual(metrics[1], {
    label: '程序状态',
    value: '已停止',
    icon: 'fa-solid fa-heart-pulse',
    tone: 'orange',
    hint: '当前没有采集任务运行',
  })
  assert.deepEqual(metrics[3], {
    label: '鉴权状态',
    value: '未启动代理',
    icon: 'fa-solid fa-certificate',
    tone: 'orange',
    hint: '启动 MITM 后打开文章获取 key',
  })
})
