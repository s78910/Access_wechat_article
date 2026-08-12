import type { ArchiveSummary } from '../bridge/pythonApi'

type Tone = 'blue' | 'green' | 'red' | 'purple' | 'orange'

export type ArchiveSummaryStat = {
  label: string
  value: string
  tone: Tone
}

function formatCount(value: unknown) {
  const count = Number(value)
  if (!Number.isFinite(count) || count < 0) {
    return '0'
  }

  return new Intl.NumberFormat('zh-CN').format(Math.floor(count))
}

export function buildArchiveSummaryStats(
  summary: ArchiveSummary | null | undefined,
  runtimeDurationLabel = '00:00:00',
): ArchiveSummaryStat[] {
  return [
    { label: '公众号数量', value: formatCount(summary?.accountCount), tone: 'blue' },
    { label: '文章数量', value: formatCount(summary?.articleCount), tone: 'blue' },
    { label: '运行总时长', value: runtimeDurationLabel, tone: 'green' },
    { label: '存储占用', value: summary?.storageSizeLabel || '0 B', tone: 'purple' },
  ]
}
