import assert from 'node:assert/strict'
import test from 'node:test'

import {
  cacheArchiveAccount,
  cacheArchiveArticles,
  clearHistoryRecords,
  exportArchiveAccountsToExcel,
  getArchiveCacheJob,
  getHistoryRecords,
  getHistorySuggestions,
  getHistorySummary,
  getPythonStatus,
  getStartupSelfCheckStatus,
  installCaCertificate,
  listRuntimePaths,
  openArchiveArticleDirectory,
  openRuntimePath,
  checkHealthTarget,
  runStartupHealthChecks,
  runStartupSelfCheck,
  resetRuntimeConfig,
  saveRuntimeConfig,
  selectRuntimeDirectory,
  startTask,
  updateRuntimeConfig,
} from '../bridge/pythonApi.ts'

type FetchCall = {
  url: string
  init?: RequestInit
}

function installFetchMock(payload: unknown) {
  const calls: FetchCall[] = []
  const previousFetch = globalThis.fetch

  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), init })
    return new Response(JSON.stringify(payload), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    })
  }) as typeof fetch

  return {
    calls,
    restore() {
      globalThis.fetch = previousFetch
    },
  }
}

test('普通浏览器环境读取状态时调用本地 HTTP API', async () => {
  const mock = installFetchMock({ ok: true, status: 'ready', webviewExists: true, serverTime: 'now' })
  try {
    const status = await getPythonStatus()

    assert.equal(status.status, 'ready')
    assert.equal(mock.calls[0]?.url, '/api/status')
  } finally {
    mock.restore()
  }
})

test('顶部健康检测通过统一 HTTP API 执行启动检查和单项重检', async () => {
  const mock = installFetchMock({ ok: true, status: 'completed', cached: false, results: {} })
  try {
    await runStartupHealthChecks()
    await checkHealthTarget('proxy-port')

    assert.equal(mock.calls[0]?.url, '/api/health/startup')
    assert.equal(mock.calls[0]?.init?.method, 'POST')
    assert.equal(mock.calls[1]?.url, '/api/health/check')
    assert.equal(mock.calls[1]?.init?.method, 'POST')
    assert.deepEqual(JSON.parse(String(mock.calls[1]?.init?.body)), { target: 'proxy-port' })
  } finally {
    mock.restore()
  }
})

test('启动自检通过独立 HTTP API 读取状态并触发执行', async () => {
  const mock = installFetchMock({
    ok: true,
    needsSelfCheck: true,
    currentVersion: '2.1.0',
    currentDataSchemaVersion: 'v2.1',
    state: null,
    statePath: 'data/runtime/startup_self_check.json',
  })
  try {
    await getStartupSelfCheckStatus()
    await runStartupSelfCheck()

    assert.equal(mock.calls[0]?.url, '/api/startup-self-check/status')
    assert.equal(mock.calls[0]?.init?.method, 'GET')
    assert.equal(mock.calls[1]?.url, '/api/startup-self-check/run')
    assert.equal(mock.calls[1]?.init?.method, 'POST')
  } finally {
    mock.restore()
  }
})

test('runtime config save sends log level through HTTP API', async () => {
  const mock = installFetchMock({ ok: true, status: 'saved', configPath: 'data/custom.yaml' })
  try {
    const result = await saveRuntimeConfig({
      autoSaveContent: true,
      autoCleanTempFiles: true,
      autoStartProxy: true,
      enableSystemProxy: true,
      logLevel: 'WARN',
      requestIntervalSeconds: 5,
      proxy: {
        host: '127.0.0.1',
        port: 18000,
        startupDelaySeconds: 0,
        verificationUrl: 'http://mitm.it/',
      },
    })

    assert.equal(result.status, 'saved')
    assert.equal(mock.calls[0]?.url, '/api/config/save')
    assert.equal(mock.calls[0]?.init?.method, 'POST')
    const body = JSON.parse(String(mock.calls[0]?.init?.body))
    assert.equal(body.logLevel, 'WARN')
    assert.equal(body.requestIntervalSeconds, 5)
    assert.equal('retryCount' in body, false)
  } finally {
    mock.restore()
  }
})

test('普通浏览器环境启动任务时通过 HTTP API 发送任务参数', async () => {
  const mock = installFetchMock({ ok: true, status: 'running' })
  try {
    const result = await startTask({
      recordLimit: 1,
      selections: {
        articleDetail: true,
        offlineArchive: true,
        commentInfo: false,
        skipCollectedRecords: true,
      },
    })

    assert.equal(result.status, 'running')
    assert.equal(mock.calls[0]?.url, '/api/task/start')
    assert.equal(mock.calls[0]?.init?.method, 'POST')
    assert.deepEqual(JSON.parse(String(mock.calls[0]?.init?.body)), {
      recordLimit: 1,
      selections: {
        articleDetail: true,
        offlineArchive: true,
        commentInfo: false,
        skipCollectedRecords: true,
      },
    })
  } finally {
    mock.restore()
  }
})

test('一键安装 CA 证书时通过 HTTP API 触发本地安装', async () => {
  const mock = installFetchMock({
    ok: true,
    status: 'installed',
    installed: true,
    label: '已安装',
    storePath: 'Cert:\\CurrentUser\\Root',
  })
  try {
    const result = await installCaCertificate()

    assert.equal(result.status, 'installed')
    assert.equal(mock.calls[0]?.url, '/api/ca/install')
    assert.equal(mock.calls[0]?.init?.method, 'POST')
  } finally {
    mock.restore()
  }
})

test('系统配置基础目录通过 HTTP API 读取程序实际路径', async () => {
  const mock = installFetchMock({
    ok: true,
    status: 'ok',
    paths: {
      projectDir: 'D:\\project',
      outputDir: 'D:\\project\\data\\logs\\article_capture',
      storageDir: 'D:\\project\\storages',
      logDir: 'D:\\project\\data\\logs',
    },
  })
  try {
    const result = await listRuntimePaths()

    assert.equal(result.paths.projectDir, 'D:\\project')
    assert.equal(result.paths.storageDir, 'D:\\project\\storages')
    assert.equal(mock.calls[0]?.url, '/api/runtime/paths')
  } finally {
    mock.restore()
  }
})

test('系统配置浏览目录时通过 HTTP API 打开对应目录 key', async () => {
  const mock = installFetchMock({
    ok: true,
    status: 'opened',
    key: 'storageDir',
    path: 'D:\\project\\storages',
  })
  try {
    const result = await openRuntimePath('storageDir')

    assert.equal(result.status, 'opened')
    assert.equal(mock.calls[0]?.url, '/api/runtime/paths/open')
    assert.equal(mock.calls[0]?.init?.method, 'POST')
    assert.deepEqual(JSON.parse(String(mock.calls[0]?.init?.body)), { key: 'storageDir' })
  } finally {
    mock.restore()
  }
})

test('采集历史列表通过 HTTP API 传递分页和筛选参数', async () => {
  const mock = installFetchMock({
    ok: true,
    status: 'ok',
    items: [
      {
        id: 1,
        accountId: 1,
        name: '测试文章',
        account: '测试公众号',
        collectType: '文章详情',
        collectTime: '2026-06-21 11:00:00',
        recordTime: '2026-06-21 10:00',
        duration: '00:03.00',
        durationSeconds: 3,
        collectStatus: 'success',
        status: '成功',
        articleLink: 'https://mp.weixin.qq.com/s/test',
        publishedArticleTime: '2026-06-21 10:00',
        recordSummary: {
          kind: 'metrics',
          message: '',
          items: [{ key: 'read_count', label: '阅读数', value: '100001' }],
        },
      },
    ],
    total: 1,
    page: 2,
    pageSize: 15,
  })
  try {
    const result = await getHistoryRecords({
      page: 2,
      pageSize: 15,
      keyword: '测试文章',
      collectType: '文章详情',
      status: 'success',
      collectDate: '2026-06-21',
    })

    assert.equal(result.page, 2)
    assert.equal(result.items[0]?.recordSummary.items[0]?.label, '阅读数')
    assert.equal(
      mock.calls[0]?.url,
      '/api/history/records?page=2&pageSize=15&keyword=%E6%B5%8B%E8%AF%95%E6%96%87%E7%AB%A0&collectType=%E6%96%87%E7%AB%A0%E8%AF%A6%E6%83%85&status=success&collectDate=2026-06-21',
    )
  } finally {
    mock.restore()
  }
})

test('history records request includes collect date range params', async () => {
  const mock = installFetchMock({
    ok: true,
    status: 'ok',
    dbPath: 'data/sql/awa-v2.1.sqlite3',
    items: [],
    total: 0,
    page: 1,
    pageSize: 15,
  })
  try {
    await getHistoryRecords({
      collectStartDate: '2026-06-01',
      collectEndDate: '2026-06-21',
    })

    assert.equal(
      mock.calls[0]?.url,
      '/api/history/records?page=1&pageSize=15&collectStartDate=2026-06-01&collectEndDate=2026-06-21',
    )
  } finally {
    mock.restore()
  }
})

test('采集历史统计通过 HTTP API 读取真实汇总', async () => {
  const mock = installFetchMock({
    ok: true,
    status: 'ok',
    totalRecords: 20,
    successfulRecords: 20,
    savedRecords: 20,
    failedRecords: 0,
    successRate: 100,
    latestCollectDate: '2026-06-21',
    collectedArticleCount: 18,
    averageDuration: '00:03.34',
    trend: [],
  })
  try {
    const result = await getHistorySummary()

    assert.equal(result.totalRecords, 20)
    assert.equal(mock.calls[0]?.url, '/api/history/summary')
  } finally {
    mock.restore()
  }
})

test('清空采集历史通过独立 DELETE HTTP API 执行', async () => {
  const mock = installFetchMock({ ok: true, status: 'deleted', deletedCount: 3 })
  try {
    const result = await clearHistoryRecords()

    assert.equal(result.status, 'deleted')
    assert.equal(result.deletedCount, 3)
    assert.equal(mock.calls[0]?.url, '/api/history/records')
    assert.equal(mock.calls[0]?.init?.method, 'DELETE')
  } finally {
    mock.restore()
  }
})

test('采集历史关键词候选通过独立 HTTP API 读取全库候选', async () => {
  const mock = installFetchMock({
    ok: true,
    status: 'ok',
    items: ['人民日报', '人民坚持稳中求进'],
    total: 2,
  })
  try {
    const result = await getHistorySuggestions({ keyword: '人', limit: 5 })

    assert.deepEqual(result.items, ['人民日报', '人民坚持稳中求进'])
    assert.equal(mock.calls[0]?.url, '/api/history/suggestions?keyword=%E4%BA%BA&limit=5')
  } finally {
    mock.restore()
  }
})

test('数据档案选中文章缓存通过 HTTP API 创建后台任务', async () => {
  const mock = installFetchMock({
    ok: true,
    status: 'pending',
    jobId: 'job-1',
    total: 2,
    finished: 0,
    running: 0,
    concurrency: 3,
    results: [],
  })
  try {
    const result = await cacheArchiveArticles([70, 69])

    assert.equal(result.jobId, 'job-1')
    assert.equal(mock.calls[0]?.url, '/api/archive/cache/articles')
    assert.equal(mock.calls[0]?.init?.method, 'POST')
    assert.deepEqual(JSON.parse(String(mock.calls[0]?.init?.body)), { articleIds: [70, 69] })
  } finally {
    mock.restore()
  }
})

test('数据档案公众号一键缓存通过 HTTP API 创建后台任务', async () => {
  const mock = installFetchMock({
    ok: true,
    status: 'pending',
    jobId: 'job-2',
    total: 5,
    finished: 0,
    running: 0,
    concurrency: 3,
    results: [],
  })
  try {
    const result = await cacheArchiveAccount(12)

    assert.equal(result.total, 5)
    assert.equal(mock.calls[0]?.url, '/api/archive/accounts/12/cache')
    assert.equal(mock.calls[0]?.init?.method, 'POST')
  } finally {
    mock.restore()
  }
})

test('数据档案缓存任务轮询通过 HTTP API 读取任务进度', async () => {
  const mock = installFetchMock({
    ok: true,
    status: 'done',
    jobId: 'job-3',
    total: 1,
    finished: 1,
    running: 0,
    concurrency: 3,
    results: [{ articleId: 1, articleTitle: '测试文章', ok: true, status: 'done' }],
  })
  try {
    const result = await getArchiveCacheJob('job-3')

    assert.equal(result.status, 'done')
    assert.equal(mock.calls[0]?.url, '/api/archive/cache/jobs/job-3')
  } finally {
    mock.restore()
  }
})

test('数据档案打开文章归档目录时只向后端提交文章 ID', async () => {
  const mock = installFetchMock({
    ok: true,
    status: 'opened',
    articleId: 88,
    path: 'D:\\project\\storages\\公众号\\文章',
  })
  try {
    const result = await openArchiveArticleDirectory(88)

    assert.equal(result.status, 'opened')
    assert.equal(mock.calls[0]?.url, '/api/archive/articles/open-directory')
    assert.equal(mock.calls[0]?.init?.method, 'POST')
    assert.deepEqual(JSON.parse(String(mock.calls[0]?.init?.body)), { articleId: 88 })
  } finally {
    mock.restore()
  }
})

test('runtime config update only syncs current process memory through HTTP API', async () => {
  const mock = installFetchMock({ ok: true, status: 'updated' })
  try {
    const result = await updateRuntimeConfig({
      autoSaveContent: true,
      autoCleanTempFiles: true,
      autoStartProxy: false,
      enableSystemProxy: true,
      logLevel: 'INFO',
      requestIntervalSeconds: 1,
      proxy: {
        host: '127.0.0.1',
        port: 18000,
        startupDelaySeconds: 0,
        verificationUrl: 'http://mitm.it/',
      },
      values: {
        'storage.log_dir': 'data/runtime-logs',
      },
    })

    assert.equal(result.status, 'updated')
    assert.equal(mock.calls[0]?.url, '/api/config/update')
    assert.equal(mock.calls[0]?.init?.method, 'POST')
    const body = JSON.parse(String(mock.calls[0]?.init?.body))
    assert.equal(body.values['storage.log_dir'], 'data/runtime-logs')
  } finally {
    mock.restore()
  }
})

test('恢复系统默认配置通过独立 HTTP API 执行', async () => {
  const mock = installFetchMock({
    ok: true,
    status: 'restored',
    configPath: 'data/custom.yaml',
    backupPath: 'data/custom.yaml.bak',
  })
  try {
    const result = await resetRuntimeConfig()

    assert.equal(result.status, 'restored')
    assert.equal(mock.calls[0]?.url, '/api/config/reset')
    assert.equal(mock.calls[0]?.init?.method, 'POST')
    assert.deepEqual(JSON.parse(String(mock.calls[0]?.init?.body)), {})
  } finally {
    mock.restore()
  }
})

test('system config directory picker sends config key and current path through HTTP API', async () => {
  const mock = installFetchMock({
    ok: true,
    status: 'selected',
    configKey: 'storage.log_dir',
    selectedPath: 'data/custom-logs',
  })
  try {
    const result = await selectRuntimeDirectory('storage.log_dir', 'data/logs')

    assert.equal(result.status, 'selected')
    assert.equal(result.selectedPath, 'data/custom-logs')
    assert.equal(mock.calls[0]?.url, '/api/runtime/paths/select-directory')
    assert.equal(mock.calls[0]?.init?.method, 'POST')
    assert.deepEqual(JSON.parse(String(mock.calls[0]?.init?.body)), {
      configKey: 'storage.log_dir',
      currentPath: 'data/logs',
    })
  } finally {
    mock.restore()
  }
})

test('Excel 导出只提交公众号 ID，由后端使用文章存储根目录', async () => {
  const mock = installFetchMock({
    ok: true,
    status: 'ok',
    exportedFileCount: 2,
    totalRowCount: 3,
    files: [],
    missingAccountIds: [],
  })
  try {
    const result = await exportArchiveAccountsToExcel([7, 8])

    assert.equal(result.exportedFileCount, 2)
    assert.equal(mock.calls[0]?.url, '/api/archive/export/accounts')
    assert.equal(mock.calls[0]?.init?.method, 'POST')
    assert.deepEqual(JSON.parse(String(mock.calls[0]?.init?.body)), {
      accountIds: [7, 8],
    })
  } finally {
    mock.restore()
  }
})
