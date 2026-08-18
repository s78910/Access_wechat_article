export type ArchiveDistributionSource = {
  account: string
  articleCount: number
  createdAt: string
}

export type ArchiveDistributionDatum = {
  name: string
  value: number
  color: string
}

export type ArchiveOverview = {
  accountCount: number
  articleCount: number
  topAccountName: string
  topAccountArticleCount: number
  latestCollectDate: string
}

const ARCHIVE_DISTRIBUTION_COLORS = [
  '#2d75d6',
  '#2f9b8f',
  '#7868d8',
  '#df9540',
  '#d85c64',
  '#8ca1ba',
]

const ARCHIVE_DISTRIBUTION_FALLBACK_COLOR = '#8ca1ba'

function normalizeArticleCount(value: number) {
  return Number.isFinite(value) ? Math.max(0, Math.floor(value)) : 0
}

function sortByArticleCount(rows: ArchiveDistributionSource[]) {
  return rows
    .map((row) => ({
      name: row.account || '未知公众号',
      value: normalizeArticleCount(row.articleCount),
    }))
    .filter((row) => row.value > 0)
    .sort((left, right) => right.value - left.value || left.name.localeCompare(right.name, 'zh-CN'))
}

// 仅展示记录最多的公众号，其余聚合为“其他”，避免图例过长挤压详情区域。
export function buildArchiveDistribution(rows: ArchiveDistributionSource[], limit = 5): ArchiveDistributionDatum[] {
  const rankedRows = sortByArticleCount(rows)
  const safeLimit = Math.max(1, Math.floor(limit))
  const visibleRows = rankedRows.slice(0, safeLimit)
  const remainingValue = rankedRows.slice(safeLimit).reduce((total, item) => total + item.value, 0)
  const distributionRows = remainingValue > 0
    ? [...visibleRows, { name: '其他', value: remainingValue }]
    : visibleRows

  return distributionRows.map((item, index) => ({
    ...item,
    color: ARCHIVE_DISTRIBUTION_COLORS[index % ARCHIVE_DISTRIBUTION_COLORS.length] ?? ARCHIVE_DISTRIBUTION_FALLBACK_COLOR,
  }))
}

export function buildArchiveOverview(rows: ArchiveDistributionSource[]): ArchiveOverview {
  const rankedRows = sortByArticleCount(rows)
  const latestCollectDate = rows
    .map((row) => row.createdAt)
    .filter((value) => /^\d{4}-\d{2}-\d{2}$/.test(value))
    .sort((left, right) => right.localeCompare(left))[0] || '-'

  return {
    accountCount: rows.length,
    articleCount: rankedRows.reduce((total, item) => total + item.value, 0),
    topAccountName: rankedRows[0]?.name || '-',
    topAccountArticleCount: rankedRows[0]?.value || 0,
    latestCollectDate,
  }
}
