import type { VxeSelectPropTypes } from 'vxe-pc-ui'

export type HistorySuggestionOption = {
  label: string
  value: string
}

export type HistorySuggestionQuery = {
  keyword: string
  limit: number
}

export type LoadHistorySuggestions = (query: HistorySuggestionQuery) => Promise<void> | void

export function buildHistorySuggestionOptions(items: string[]): HistorySuggestionOption[] {
  return items.map((item) => ({ label: item, value: item }))
}

export function createHistorySuggestionRemoteConfig(
  loadSuggestions: LoadHistorySuggestions,
): VxeSelectPropTypes.RemoteConfig {
  return {
    enabled: true,
    autoLoad: true,
    clearOnClose: false,
    // VXE 的搜索框值不会直接写入 v-model，这里专门把搜索词转成后端全库候选查询。
    queryMethod({ searchValue }) {
      return loadSuggestions({
        keyword: String(searchValue || '').trim(),
        limit: 30,
      })
    },
  }
}
