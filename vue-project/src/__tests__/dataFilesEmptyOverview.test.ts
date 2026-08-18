import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'
import test from 'node:test'

const currentDir = dirname(fileURLToPath(import.meta.url))
const pagePath = resolve(currentDir, '../pages/DataFilesPage.vue')
const appPath = resolve(currentDir, '../App.vue')
const chartPath = resolve(currentDir, '../components/ArchiveDistributionChart.vue')
const distributionPath = resolve(currentDir, '../utils/archiveDistribution.ts')
const pageSource = readFileSync(pagePath, 'utf8')
const appSource = readFileSync(appPath, 'utf8')

test('记录详情未选择公众号时区分加载、错误、首次使用和统计概览', () => {
  assert.match(pageSource, /import ArchiveDistributionChart from '..\/components\/ArchiveDistributionChart\.vue'/)
  assert.match(pageSource, /const emit = defineEmits<\{[\s\S]*navigate:/)
  assert.match(pageSource, /const archiveAccountsLoading = ref\(true\)/)
  assert.match(pageSource, /<div v-if="archiveAccountsLoading"[\s\S]*<ASkeleton/)
  assert.match(pageSource, /<AResult[\s\S]*v-else-if="archiveAccountsError"/)
  assert.match(pageSource, /v-else-if="archiveDistributionData\.length === 0"[\s\S]*暂无归档数据/)
  assert.match(pageSource, /@click="emit\('navigate', 'home'\)"[\s\S]*前往主服务/)
  assert.match(pageSource, /<ArchiveDistributionChart[\s\S]*:data="archiveDistributionData"/)
  assert.match(
    pageSource,
    /<div v-else class="record-empty record-overview-empty">\s*<div class="archive-overview-guide" role="note">[\s\S]*选择左侧公众号查看记录详情/,
  )
  assert.match(pageSource, /点击左侧列表中的「预览」后，可查看文章标题、发布时间、归档大小和操作入口。/)
  assert.match(pageSource, /class="archive-overview-guide-steps" aria-label="查看记录详情步骤"[\s\S]*选择公众号[\s\S]*点击预览[\s\S]*查看详情/)
  assert.doesNotMatch(pageSource, /覆盖 \{\{ archiveOverview\.accountCount \}\} 个公众号/)
  assert.match(appSource, /<DataFilesPage[\s\S]*@navigate="selectPage"/)
})

test('归档分布工具聚合 Top N、其他与概览摘要', async () => {
  assert.ok(existsSync(distributionPath), 'archiveDistribution.ts should exist')
  const moduleUrl = `${pathToFileURL(distributionPath).href}?test=${Date.now()}`
  const { buildArchiveDistribution, buildArchiveOverview } = await import(moduleUrl)
  const rows = [
    { account: '甲', articleCount: 10, createdAt: '2026-08-15' },
    { account: '乙', articleCount: 8, createdAt: '2026-08-17' },
    { account: '丙', articleCount: 3, createdAt: '2026-08-12' },
    { account: '丁', articleCount: 2, createdAt: '-' },
  ]

  assert.deepEqual(buildArchiveDistribution(rows, 2).map(({ name, value }: { name: string; value: number }) => ({ name, value })), [
    { name: '甲', value: 10 },
    { name: '乙', value: 8 },
    { name: '其他', value: 5 },
  ])
  assert.ok(
    buildArchiveDistribution(rows, 2).every(({ color }: { color: string }) => /^#[0-9a-f]{6}$/i.test(color)),
    '每个分布图数据都应带有稳定色值',
  )
  assert.deepEqual(buildArchiveOverview(rows), {
    accountCount: 4,
    articleCount: 23,
    topAccountName: '甲',
    topAccountArticleCount: 10,
    latestCollectDate: '2026-08-17',
  })
})

test('归档分布图使用 AntV G2 环形坐标并正确销毁实例', () => {
  assert.ok(existsSync(chartPath), 'ArchiveDistributionChart.vue should exist')
  const chartSource = readFileSync(chartPath, 'utf8')

  assert.match(chartSource, /import \{ Chart \} from '@antv\/g2'/)
  assert.match(chartSource, /new Chart\(/)
  assert.match(chartSource, /coordinate:\s*\{\s*type:\s*'theta'/)
  assert.match(chartSource, /innerRadius:/)
  assert.match(chartSource, /chart\.destroy\(\)/)
  assert.match(chartSource, /watch\(/)
})
