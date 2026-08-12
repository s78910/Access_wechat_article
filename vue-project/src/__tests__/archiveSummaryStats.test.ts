import assert from 'node:assert/strict'
import test from 'node:test'

import { buildArchiveSummaryStats } from '../utils/archiveSummaryStats.ts'

test('归档统计卡片复用 archive summary 的真实字段，并使用运行时长覆盖总时长', () => {
  const stats = buildArchiveSummaryStats({
    ok: true,
    status: 'ok',
    accountCount: 56,
    articleCount: 2468,
    dataType: 'JSON',
    storageSizeBytes: 163913072,
    storageSizeLabel: '156.32 MB',
    storageRoot: 'D:/repo/storages',
    dbPath: 'D:/repo/data/awa_public.sqlite3',
  }, '00:01:05')

  assert.deepEqual(stats.map((item) => [item.label, item.value]), [
    ['公众号数量', '56'],
    ['文章数量', '2,468'],
    ['运行总时长', '00:01:05'],
    ['存储占用', '156.32 MB'],
  ])
})

test('归档统计卡片在 summary 未加载时显示安全兜底值', () => {
  const stats = buildArchiveSummaryStats(null, '00:00:00')

  assert.deepEqual(stats.map((item) => item.value), ['0', '0', '00:00:00', '0 B'])
})
