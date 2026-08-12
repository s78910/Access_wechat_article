import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildHistorySuggestionOptions,
  createHistorySuggestionRemoteConfig,
} from '../utils/historySuggestions.ts'

test('采集历史候选选项保持 label 和 value 一致，避免页面依赖表格分页数据', () => {
  assert.deepEqual(buildHistorySuggestionOptions(['新华社', '早知天下事']), [
    { label: '新华社', value: '新华社' },
    { label: '早知天下事', value: '早知天下事' },
  ])
})

test('采集历史关键词远程搜索会把 VXE 搜索词传给全库候选加载函数', async () => {
  const calls: Array<{ keyword: string; limit: number }> = []
  const remoteConfig = createHistorySuggestionRemoteConfig(async (query) => {
    calls.push(query)
  })

  await remoteConfig.queryMethod?.({
    searchValue: '人',
    value: undefined,
    $select: {} as never,
  })

  assert.equal(remoteConfig.enabled, true)
  assert.equal(remoteConfig.autoLoad, true)
  assert.equal(remoteConfig.clearOnClose, false)
  assert.deepEqual(calls, [{ keyword: '人', limit: 30 }])
})
