<script setup lang="ts">
import AppIcon from '../components/AppIcon.vue'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { ArchiveAccountItem, ArchiveArticleItem, ArchiveCacheJob, ArchiveCacheResultItem } from '../bridge/pythonApi'
import {
  cacheArchiveAccount,
  cacheArchiveArticles,
  deleteArchiveAccount,
  deleteArchiveAll,
  deleteArchiveArticles,
  getArchiveCacheJob,
  exportArchiveAccountsToExcel,
  listArchiveAccountArticles,
  listArchiveAccounts,
  openArchiveArticleDirectory,
  openRuntimePath,
} from '../bridge/pythonApi'
import ConfirmDialog from '../components/ConfirmDialog.vue'
import type { ArchiveSummaryStat } from '../utils/archiveSummaryStats'
import { calculatePagedTableRowHeight } from '../utils/pagedTableLayout'

type RecordRow = {
  id: number
  rowIndex: number
  title: string
  link: string
  archiveDir: string
  publishedAt: string
  size: string
}

type FileRow = {
  id: number
  account: string
  createdAt: string
  articleCount: number
  savedCount: number
  failedCount: number
}

type DeleteDialogMode = 'records' | 'account' | 'all'

type DeleteDialogState = {
  open: boolean
  mode: DeleteDialogMode
  title: string
  description: string
  summaryItems: Array<{ label: string; value: string }>
  detailTitle: string
  detailItems: string[]
  warning: string
  confirmText: string
  targetArticleIds: number[]
  targetAccount: FileRow | null
  errorMessage: string
}

type CacheToastTone = 'success' | 'warning' | 'error'

type CacheToast = {
  id: string
  message: string
  tone: CacheToastTone
}

const props = defineProps<{
  summaryStats: ArchiveSummaryStat[]
}>()

const selectedAccount = ref('')
const selectedCollectStartDate = ref('')
const selectedCollectEndDate = ref('')
const selectedPreviewFile = ref<FileRow | null>(null)
const selectedRecordIndexes = ref<number[]>([])
const fileListRows = ref<FileRow[]>([])
const recordRows = ref<RecordRow[]>([])
const recordTotal = ref(0)
const archiveAccountsLoading = ref(false)
const archiveAccountsError = ref('')
const archiveArticlesLoading = ref(false)
const archiveArticlesError = ref('')
const archiveDeleting = ref(false)
const archiveCaching = ref(false)
const archiveExporting = ref(false)
const activeCacheJobId = ref('')
const cacheJobSnapshot = ref<ArchiveCacheJob | null>(null)
const activeProcessIndex = ref(0)
const cacheProcessRotationPaused = ref(false)
const notifiedCacheArticleIds = ref<number[]>([])
const cacheToasts = ref<CacheToast[]>([])
const batchExportDialogOpen = ref(false)
const selectedExportAccountIds = ref<number[]>([])
const deleteDialog = ref<DeleteDialogState>({
  open: false,
  mode: 'records',
  title: '',
  description: '',
  summaryItems: [],
  detailTitle: '',
  detailItems: [],
  warning: '',
  confirmText: '确认删除',
  targetArticleIds: [],
  targetAccount: null,
  errorMessage: '',
})
const fileCurrentPage = ref(1)
const filePageSize = ref(10)
const recordCurrentPage = ref(1)
const recordPageSize = ref(10)
const accountTableWrapRef = ref<HTMLElement | null>(null)
const recordTableWrapRef = ref<HTMLElement | null>(null)
const pagerLayouts: Array<'PrevPage' | 'JumpNumber' | 'NextPage'> = ['PrevPage', 'JumpNumber', 'NextPage']
const archiveTablePageSize = 10
let archiveArticlesRequestId = 0
let cachePollingTimer: number | undefined
let cacheProcessRotationTimer: number | undefined
let archiveTableResizeObserver: ResizeObserver | undefined

type PagerChangeParams = {
  currentPage: number
  pageSize: number
}

const accountOptions = computed(() => {
  return Array.from(new Set(fileListRows.value.map((file) => file.account)))
})

const accountSelectOptions = computed(() => {
  return accountOptions.value.map((account) => ({
    label: account,
    value: account,
  }))
})

const archiveMetricLabels = new Set(['文章数量', '存储占用'])

const archiveMetricIcons: Record<string, string> = {
  文章数量: 'fa-regular fa-file-lines',
  存储占用: 'fa-solid fa-database',
}

const archiveMetrics = computed(() => props.summaryStats.filter((item) => archiveMetricLabels.has(item.label)).map((item) => ({
  ...item,
  icon: archiveMetricIcons[item.label] || 'fa-solid fa-database',
})))

const cacheTaskStatusValue = computed(() => {
  const job = cacheJobSnapshot.value
  if (archiveCaching.value && !job) {
    return '正在准备'
  }
  if (!job) {
    return '当前空闲'
  }
  if (job.status === 'pending') {
    return '正在准备'
  }
  if (job.status === 'running') {
    return `${job.processed} / ${job.requestedTotal}`
  }
  if (job.status === 'done') {
    return `${job.requestedTotal} / ${job.requestedTotal}`
  }
  if (job.status === 'partial_failed') {
    return `${job.processed} / ${job.requestedTotal}`
  }
  return '任务异常'
})

const cacheTaskStatusSummary = computed(() => {
  const job = cacheJobSnapshot.value
  if (archiveCaching.value && !job) {
    return '正在创建缓存任务'
  }
  if (!job) {
    return '暂无缓存任务'
  }
  if (job.status === 'pending') {
    return `等待执行 ${job.requestedTotal} 篇`
  }
  if (job.status === 'running') {
    return `运行 ${job.running} · 排队 ${job.queued} · 跳过 ${job.skipped} · 失败 ${job.failed}`
  }
  if (job.status === 'done') {
    return `已完成 ${job.processed} 篇 · 跳过 ${job.skipped} 篇`
  }
  if (job.status === 'partial_failed') {
    return `已处理 ${job.processed} 篇 · 失败 ${job.failed} 篇`
  }
  return job.message || '缓存任务未正常完成'
})

const cacheTaskTone = computed(() => {
  const status = cacheJobSnapshot.value?.status
  if (status === 'done') {
    return 'green'
  }
  if (status === 'partial_failed') {
    return 'orange'
  }
  if (status === 'failed' || status === 'missing') {
    return 'red'
  }
  return archiveCaching.value ? 'blue' : 'purple'
})

const activeCacheProcesses = computed(() => cacheJobSnapshot.value?.activeProcesses || [])

const visibleActiveProcess = computed(() => {
  const processes = activeCacheProcesses.value
  if (processes.length === 0) {
    return null
  }
  return processes[activeProcessIndex.value % processes.length]
})

const cacheActiveProcessSummary = computed(() => {
  const process = visibleActiveProcess.value
  if (process) {
    return `${process.step} · ${process.elapsedSeconds.toFixed(1)} 秒`
  }
  if (archiveCaching.value && !cacheJobSnapshot.value) {
    return '正在等待缓存子进程启动'
  }
  if (cacheJobSnapshot.value?.status === 'running') {
    return cacheJobSnapshot.value.queued > 0 ? '正在等待下一个子进程' : '正在整理缓存结果'
  }
  return '暂无活跃子进程'
})

const filteredFileRows = computed(() => {
  return fileListRows.value.filter((file) => {
    const collectDate = file.createdAt.slice(0, 10)
    const matchAccount = !selectedAccount.value || file.account === selectedAccount.value
    const matchStartDate = !selectedCollectStartDate.value || collectDate >= selectedCollectStartDate.value
    const matchEndDate = !selectedCollectEndDate.value || collectDate <= selectedCollectEndDate.value

    return matchAccount && matchStartDate && matchEndDate
  })
})

const filePagerRows = computed(() => {
  return filteredFileRows.value
})

const filePagerTotal = computed(() => {
  return filePagerRows.value.length
})

const batchExportRows = computed(() => {
  return fileListRows.value
})

const recordPagerTotal = computed(() => {
  return selectedPreviewFile.value ? recordTotal.value : 0
})

const visibleFileRows = computed(() => {
  const start = (fileCurrentPage.value - 1) * filePageSize.value
  return filePagerRows.value.slice(start, start + filePageSize.value)
})

const visibleRecordRows = computed(() => {
  return recordRows.value
})

const filePlaceholderRowCount = computed(() => {
  if (archiveAccountsLoading.value || archiveAccountsError.value || visibleFileRows.value.length === 0) {
    return 0
  }
  return Math.max(archiveTablePageSize - visibleFileRows.value.length, 0)
})

const recordPlaceholderRowCount = computed(() => {
  if (archiveArticlesLoading.value || archiveArticlesError.value || visibleRecordRows.value.length === 0) {
    return 0
  }
  return Math.max(archiveTablePageSize - visibleRecordRows.value.length, 0)
})

const allRecordIndexes = computed(() => {
  const pageStartIndex = (recordCurrentPage.value - 1) * recordPageSize.value
  return recordRows.value.map((_, index) => pageStartIndex + index)
})

const selectedRecordCount = computed(() => {
  return selectedRecordIndexes.value.length
})

const selectedRecordIds = computed(() => {
  const selectedIndexes = new Set(selectedRecordIndexes.value)
  return recordRows.value.filter((record) => selectedIndexes.has(record.rowIndex)).map((record) => record.id)
})

const isAllRecordsSelected = computed(() => {
  return allRecordIndexes.value.length > 0 && selectedRecordCount.value === allRecordIndexes.value.length
})

const isSomeRecordsSelected = computed(() => {
  return selectedRecordCount.value > 0 && !isAllRecordsSelected.value
})

const selectedExportCount = computed(() => {
  return selectedExportAccountIds.value.length
})

const selectedExportRecordCount = computed(() => {
  const selectedIds = new Set(selectedExportAccountIds.value)
  return batchExportRows.value.reduce((total, file) => {
    return selectedIds.has(file.id) ? total + file.articleCount : total
  }, 0)
})

const isAllExportAccountsSelected = computed(() => {
  return batchExportRows.value.length > 0 && selectedExportCount.value === batchExportRows.value.length
})

const isSomeExportAccountsSelected = computed(() => {
  return selectedExportCount.value > 0 && !isAllExportAccountsSelected.value
})

function formatArchiveAccountRow(item: ArchiveAccountItem): FileRow {
  const latestCollectTime = item.latestCollectTime || item.updatedTime || item.createdTime || '-'

  return {
    id: item.id,
    account: item.accountName || '未知公众号',
    createdAt: formatAccountCollectDate(latestCollectTime),
    articleCount: item.articleCount,
    savedCount: item.savedCount,
    failedCount: item.failedCount,
  }
}

function formatAccountCollectDate(value: string) {
  const matched = value.match(/^\d{4}-\d{2}-\d{2}/)
  return matched ? matched[0] : '-'
}

function formatArchiveArticleRow(item: ArchiveArticleItem, index: number): RecordRow {
  return {
    id: item.id,
    rowIndex: (recordCurrentPage.value - 1) * recordPageSize.value + index,
    title: item.title || '未命名文章',
    link: item.articleLink || '',
    archiveDir: item.archiveDir || '',
    publishedAt: item.publishedArticleTime || '-',
    size: item.sizeLabel || '0 B',
  }
}

function truncateAccountName(account: string) {
  const chars = Array.from(account || '')
  return chars.length > 10 ? `${chars.slice(0, 9).join('')}...` : account
}

async function loadArchiveAccounts() {
  archiveAccountsLoading.value = true
  archiveAccountsError.value = ''

  try {
    const result = await listArchiveAccounts()
    fileListRows.value = result.items.map(formatArchiveAccountRow)
  } catch (error) {
    archiveAccountsError.value = error instanceof Error ? error.message : '读取公众号列表失败'
    fileListRows.value = []
  } finally {
    archiveAccountsLoading.value = false
  }
}

function toggleAllRecords(event: Event) {
  const checked = (event.target as HTMLInputElement).checked
  selectedRecordIndexes.value = checked ? [...allRecordIndexes.value] : []
}

// 记录详情按后端分页加载；每次打开或翻页时只让后端计算当前页文章目录大小。
async function loadArchiveArticles(file: FileRow, page = recordCurrentPage.value, pageSize = recordPageSize.value) {
  const requestId = ++archiveArticlesRequestId
  recordRows.value = []
  recordTotal.value = 0
  selectedRecordIndexes.value = []
  archiveArticlesLoading.value = true
  archiveArticlesError.value = ''

  try {
    const result = await listArchiveAccountArticles(file.id, page, pageSize)
    if (requestId !== archiveArticlesRequestId) {
      return
    }
    recordCurrentPage.value = result.page
    recordPageSize.value = result.pageSize
    recordTotal.value = result.total
    recordRows.value = result.items.map(formatArchiveArticleRow)
  } catch (error) {
    if (requestId !== archiveArticlesRequestId) {
      return
    }
    archiveArticlesError.value = error instanceof Error ? error.message : '读取记录详情失败'
  } finally {
    if (requestId === archiveArticlesRequestId) {
      archiveArticlesLoading.value = false
    }
  }
}

async function previewFile(file: FileRow) {
  selectedPreviewFile.value = file
  recordCurrentPage.value = 1
  recordPageSize.value = 10
  await loadArchiveArticles(file, 1, recordPageSize.value)
}

function handleFilePageChange({ currentPage, pageSize }: PagerChangeParams) {
  fileCurrentPage.value = currentPage
  filePageSize.value = pageSize
}

function handleRecordPageChange({ currentPage, pageSize }: PagerChangeParams) {
  recordCurrentPage.value = currentPage
  recordPageSize.value = pageSize
  if (selectedPreviewFile.value) {
    void loadArchiveArticles(selectedPreviewFile.value, currentPage, pageSize)
  }
}

async function refreshArchiveViewAfterDelete() {
  await loadArchiveAccounts()
  if (!selectedPreviewFile.value) {
    return
  }

  const exists = fileListRows.value.some((file) => file.id === selectedPreviewFile.value?.id)
  if (!exists) {
    selectedPreviewFile.value = null
    recordRows.value = []
    recordTotal.value = 0
    selectedRecordIndexes.value = []
    return
  }

  const nextPage = Math.min(recordCurrentPage.value, Math.max(1, Math.ceil(recordPagerTotal.value / recordPageSize.value)))
  await loadArchiveArticles(selectedPreviewFile.value, nextPage, recordPageSize.value)
}

function formatDeleteFailureMessage(result: Awaited<ReturnType<typeof deleteArchiveArticles>>) {
  if (result.ok) {
    return ''
  }
  const firstFailure = result.failures[0]
  return firstFailure ? `部分本地目录删除失败：${firstFailure.path}` : '删除时存在未完成项，请查看后端日志'
}

function showCacheToast(message: string, tone: CacheToastTone = 'success') {
  const toast: CacheToast = {
    id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
    message,
    tone,
  }
  cacheToasts.value = [...cacheToasts.value, toast].slice(-4)
  window.setTimeout(() => {
    cacheToasts.value = cacheToasts.value.filter((item) => item.id !== toast.id)
  }, 1800)
}

async function handleOpenStorageDirectory() {
  try {
    const result = await openRuntimePath('storageDir')
    showCacheToast(result.message || '已打开数据归档目录。', result.ok ? 'success' : 'error')
  } catch (error) {
    showCacheToast(error instanceof Error ? error.message : '打开数据归档目录失败', 'error')
  }
}

function openArticleLink(record: RecordRow) {
  if (!record.link) {
    return
  }
  window.open(record.link, '_blank', 'noopener,noreferrer')
}

async function openRecordArchiveDirectory(record: RecordRow) {
  try {
    const result = await openArchiveArticleDirectory(record.id)
    showCacheToast(result.message || '已打开文章归档目录。', result.ok ? 'success' : 'error')
  } catch (error) {
    showCacheToast(error instanceof Error ? error.message : '打开文章归档目录失败', 'error')
  }
}

function clearCachePolling() {
  if (cachePollingTimer !== undefined) {
    window.clearInterval(cachePollingTimer)
    cachePollingTimer = undefined
  }
}

function clearCacheProcessRotation() {
  if (cacheProcessRotationTimer !== undefined) {
    window.clearInterval(cacheProcessRotationTimer)
    cacheProcessRotationTimer = undefined
  }
}

function startCacheProcessRotation() {
  clearCacheProcessRotation()
  cacheProcessRotationTimer = window.setInterval(() => {
    if (cacheProcessRotationPaused.value || activeCacheProcesses.value.length <= 1) {
      return
    }
    activeProcessIndex.value = (activeProcessIndex.value + 1) % activeCacheProcesses.value.length
  }, 2500)
}

function pauseCacheProcessRotation() {
  cacheProcessRotationPaused.value = true
}

function resumeCacheProcessRotation() {
  cacheProcessRotationPaused.value = false
}

async function refreshArchiveViewAfterCache() {
  await loadArchiveAccounts()
  if (selectedPreviewFile.value) {
    await loadArchiveArticles(selectedPreviewFile.value, recordCurrentPage.value, recordPageSize.value)
  }
}

function notifyCacheResults(results: ArchiveCacheResultItem[]) {
  const notified = new Set(notifiedCacheArticleIds.value)
  for (const item of results) {
    if (notified.has(item.articleId)) {
      continue
    }
    notified.add(item.articleId)
    if (item.ok) {
      showCacheToast(`${item.articleTitle} 已缓存`, 'success')
    } else {
      showCacheToast(`${item.articleTitle} 缓存失败`, 'error')
    }
  }
  notifiedCacheArticleIds.value = Array.from(notified)
}

async function handleCacheJobSnapshot(job: ArchiveCacheJob) {
  cacheJobSnapshot.value = job
  notifyCacheResults(job.results)
  const finished = ['done', 'partial_failed', 'failed', 'missing'].includes(job.status)
  if (!finished) {
    return
  }

  clearCachePolling()
  archiveCaching.value = false
  activeCacheJobId.value = ''
  if (job.status === 'done' && job.total === 0) {
    showCacheToast(job.message || '没有可缓存的文章', 'warning')
  } else if (job.status === 'done' && job.skipped > 0) {
    showCacheToast(job.message || `新增缓存 ${job.finished} 篇，跳过已有缓存 ${job.skipped} 篇。`, 'success')
  } else if (job.status === 'partial_failed') {
    showCacheToast(job.message || '部分文章缓存失败', 'warning')
  } else if (job.status === 'failed' || job.status === 'missing') {
    showCacheToast(job.message || '缓存任务失败', 'error')
  }
  await refreshArchiveViewAfterCache()
}

async function pollCacheJob(jobId: string) {
  try {
    const job = await getArchiveCacheJob(jobId)
    await handleCacheJobSnapshot(job)
  } catch (error) {
    clearCachePolling()
    archiveCaching.value = false
    activeCacheJobId.value = ''
    showCacheToast(error instanceof Error ? error.message : '读取缓存任务状态失败', 'error')
  }
}

function startCachePolling(jobId: string) {
  clearCachePolling()
  activeCacheJobId.value = jobId
  cachePollingTimer = window.setInterval(() => {
    void pollCacheJob(jobId)
  }, 1000)
  void pollCacheJob(jobId)
}

async function startArchiveCacheJob(jobPromise: Promise<ArchiveCacheJob>) {
  if (archiveCaching.value) {
    showCacheToast('已有缓存任务正在执行', 'warning')
    return
  }
  archiveCaching.value = true
  cacheJobSnapshot.value = null
  activeProcessIndex.value = 0
  notifiedCacheArticleIds.value = []
  try {
    const job = await jobPromise
    await handleCacheJobSnapshot(job)
    if (job.total === 0) {
      return
    }
    if (!['done', 'partial_failed', 'failed', 'missing'].includes(job.status)) {
      startCachePolling(job.jobId)
    }
  } catch (error) {
    archiveCaching.value = false
    showCacheToast(error instanceof Error ? error.message : '创建缓存任务失败', 'error')
  }
}

async function cacheSelectedRecords() {
  const articleIds = selectedRecordIds.value
  if (articleIds.length === 0) {
    showCacheToast('请先选择要缓存的文章', 'warning')
    return
  }
  await startArchiveCacheJob(cacheArchiveArticles(articleIds))
}

async function cacheAccountArticles(file: FileRow) {
  await startArchiveCacheJob(cacheArchiveAccount(file.id))
}

function openBatchExportDialog() {
  // 批量导出默认全选已有公众号，用户可以在弹窗内再缩小范围。
  selectedExportAccountIds.value = batchExportRows.value.map((file) => file.id)
  batchExportDialogOpen.value = true
}

function closeBatchExportDialog() {
  if (archiveExporting.value) {
    return
  }
  batchExportDialogOpen.value = false
}

function toggleAllExportAccounts(event: Event) {
  const checked = (event.target as HTMLInputElement).checked
  selectedExportAccountIds.value = checked ? batchExportRows.value.map((file) => file.id) : []
}

async function handleBatchExportExcel() {
  if (selectedExportAccountIds.value.length === 0) {
    showCacheToast('请先选择要导出的公众号', 'warning')
    return
  }
  archiveExporting.value = true
  try {
    const result = await exportArchiveAccountsToExcel([...selectedExportAccountIds.value])
    if (!result.ok) {
      const message = result.message || '导出 Excel 失败'
      showCacheToast(message, 'error')
      return
    }
    batchExportDialogOpen.value = false
    showCacheToast(
      result.message || `已导出 ${result.exportedFileCount} 个 Excel 文件，共 ${result.totalRowCount} 条记录`,
      result.status === 'partial-failed' ? 'warning' : 'success',
    )
  } catch (error) {
    const message = error instanceof Error ? error.message : '导出 Excel 失败'
    showCacheToast(message, message.includes('取消') ? 'warning' : 'error')
  } finally {
    archiveExporting.value = false
  }
}

function closeDeleteDialog() {
  if (archiveDeleting.value) {
    return
  }
  deleteDialog.value.open = false
  deleteDialog.value.errorMessage = ''
}

function openDeleteSelectedRecordsDialog() {
  if (!selectedPreviewFile.value || archiveDeleting.value) {
    return
  }
  const articleIds = selectedRecordIds.value
  if (articleIds.length === 0) {
    deleteDialog.value = {
      ...deleteDialog.value,
      open: true,
      mode: 'records',
      title: '请先选择记录',
      description: '需要先在记录详情表格中勾选一条或多条文章记录，才能执行删除。',
      summaryItems: [
        { label: '当前公众号', value: selectedPreviewFile.value.account },
        { label: '已选择', value: '0 条' },
      ],
      detailTitle: '',
      detailItems: [],
      warning: '未选择记录时不会删除任何数据库记录或本地归档目录。',
      confirmText: '我知道了',
      targetArticleIds: [],
      targetAccount: null,
      errorMessage: '',
    }
    return
  }

  const selectedIndexes = new Set(selectedRecordIndexes.value)
  const selectedRows = recordRows.value.filter((record) => selectedIndexes.has(record.rowIndex))
  deleteDialog.value = {
    open: true,
    mode: 'records',
    title: `删除选中的 ${articleIds.length} 条记录`,
    description: `将删除公众号「${selectedPreviewFile.value.account}」下选中的文章记录。`,
    summaryItems: [
      { label: '当前公众号', value: selectedPreviewFile.value.account },
      { label: '文章记录', value: `${articleIds.length} 条` },
      { label: '数据库影响', value: '删除 awa_public_articles 对应行' },
      { label: '本地存储', value: '删除文章目录及 _1 等重复目录' },
    ],
    detailTitle: '将删除的记录',
    detailItems: selectedRows.map((record) => `#${record.rowIndex + 1} ${record.title}`).slice(0, 5),
    warning: '删除后会同时清理本地归档目录；同一篇文章的重复目录会一并删除，无法从页面恢复。',
    confirmText: '确认删除记录',
    targetArticleIds: articleIds,
    targetAccount: null,
    errorMessage: '',
  }
}

async function executeDeleteSelectedRecords(articleIds: number[]) {
  archiveDeleting.value = true
  try {
    const result = await deleteArchiveArticles(articleIds)
    const failureMessage = formatDeleteFailureMessage(result)
    if (failureMessage) {
      deleteDialog.value.errorMessage = failureMessage
      return
    }
    deleteDialog.value.open = false
    await refreshArchiveViewAfterDelete()
  } catch (error) {
    deleteDialog.value.errorMessage = error instanceof Error ? error.message : '删除记录失败'
  } finally {
    archiveDeleting.value = false
  }
}

function openDeleteAccountDialog(file: FileRow) {
  if (archiveDeleting.value) {
    return
  }

  deleteDialog.value = {
    open: true,
    mode: 'account',
    title: `删除公众号「${file.account}」记录`,
    description: '将先删除该公众号下全部文章记录及本地归档，再删除公众号记录。',
    summaryItems: [
      { label: '公众号', value: file.account },
      { label: '文章记录', value: `${file.articleCount} 条` },
      { label: '成功记录', value: `${file.savedCount} 条` },
      { label: '失败记录', value: `${file.failedCount} 条` },
    ],
    detailTitle: '删除顺序',
    detailItems: [
      '逐篇删除 awa_public_articles 中的文章记录',
      '删除每篇文章本地目录及 _1 等重复目录',
      '最后删除 awa_public_accounts 中的公众号记录',
    ],
    warning: '这会删除该公众号下所有数据档案内容，包括本地存储文件；删除后无法从页面恢复。',
    confirmText: '确认删除公众号记录',
    targetArticleIds: [],
    targetAccount: file,
    errorMessage: '',
  }
}

async function executeDeleteAccount(file: FileRow) {
  archiveDeleting.value = true
  try {
    const result = await deleteArchiveAccount(file.id)
    const failureMessage = formatDeleteFailureMessage(result)
    if (failureMessage) {
      deleteDialog.value.errorMessage = failureMessage
      return
    }
    deleteDialog.value.open = false
    if (selectedPreviewFile.value?.id === file.id) {
      selectedPreviewFile.value = null
      recordRows.value = []
      recordTotal.value = 0
      selectedRecordIndexes.value = []
    }
    await loadArchiveAccounts()
  } catch (error) {
    deleteDialog.value.errorMessage = error instanceof Error ? error.message : '删除公众号失败'
  } finally {
    archiveDeleting.value = false
  }
}

function openDeleteAllArchivesDialog() {
  if (archiveDeleting.value) {
    return
  }

  const articleTotal = fileListRows.value.reduce((total, file) => total + file.articleCount, 0)
  deleteDialog.value = {
    open: true,
    mode: 'all',
    title: '删除全部数据档案',
    description: '将遍历公众号列表，删除全部文章记录、公众号记录和对应本地归档目录。',
    summaryItems: [
      { label: '公众号', value: `${fileListRows.value.length} 个` },
      { label: '文章记录', value: `${articleTotal} 条` },
      { label: '数据库影响', value: '清空 awa_public_articles / awa_public_accounts' },
      { label: '本地存储', value: '清理全部匹配归档目录' },
    ],
    detailTitle: '将删除的公众号',
    detailItems: fileListRows.value.map((file) => `${file.account}（${file.articleCount} 条）`).slice(0, 5),
    warning: '这是最高风险操作，会删除当前数据库中全部数据档案及匹配的本地存储目录，无法从页面恢复。',
    confirmText: '确认全部删除',
    targetArticleIds: [],
    targetAccount: null,
    errorMessage: '',
  }
}

async function executeDeleteAllArchives() {
  archiveDeleting.value = true
  try {
    const result = await deleteArchiveAll()
    const failureMessage = formatDeleteFailureMessage(result)
    if (failureMessage) {
      deleteDialog.value.errorMessage = failureMessage
      return
    }
    deleteDialog.value.open = false
    selectedPreviewFile.value = null
    selectedRecordIndexes.value = []
    recordRows.value = []
    recordTotal.value = 0
    await loadArchiveAccounts()
  } catch (error) {
    deleteDialog.value.errorMessage = error instanceof Error ? error.message : '全部删除失败'
  } finally {
    archiveDeleting.value = false
  }
}

async function confirmDeleteDialog() {
  if (archiveDeleting.value) {
    return
  }
  if (deleteDialog.value.targetArticleIds.length === 0 && deleteDialog.value.mode === 'records') {
    closeDeleteDialog()
    return
  }
  if (deleteDialog.value.mode === 'records') {
    await executeDeleteSelectedRecords(deleteDialog.value.targetArticleIds)
    return
  }
  if (deleteDialog.value.mode === 'account' && deleteDialog.value.targetAccount) {
    await executeDeleteAccount(deleteDialog.value.targetAccount)
    return
  }
  if (deleteDialog.value.mode === 'all') {
    await executeDeleteAllArchives()
  }
}

function updatePagedTableRowHeight(tableWrap: HTMLElement | null) {
  if (!tableWrap) {
    return
  }

  const tableHeader = tableWrap.querySelector('thead')
  const headerHeight = tableHeader?.getBoundingClientRect().height ?? 0
  const rowHeight = calculatePagedTableRowHeight(tableWrap.clientHeight, headerHeight, archiveTablePageSize)
  if (rowHeight > 0) {
    tableWrap.style.setProperty('--paged-table-row-height', `${rowHeight}px`)
  }
}

function updateArchiveTableRowHeights() {
  updatePagedTableRowHeight(accountTableWrapRef.value)
  updatePagedTableRowHeight(recordTableWrapRef.value)
}

function observeArchiveTableWraps() {
  archiveTableResizeObserver?.disconnect()
  if (accountTableWrapRef.value) {
    archiveTableResizeObserver?.observe(accountTableWrapRef.value)
  }
  if (recordTableWrapRef.value) {
    archiveTableResizeObserver?.observe(recordTableWrapRef.value)
  }
  updateArchiveTableRowHeights()
}

watch([selectedAccount, selectedCollectStartDate, selectedCollectEndDate], () => {
  fileCurrentPage.value = 1
  selectedPreviewFile.value = null
  selectedRecordIndexes.value = []
  recordRows.value = []
  recordTotal.value = 0
  archiveArticlesError.value = ''
  archiveArticlesLoading.value = false
})

watch(selectedPreviewFile, () => {
  void nextTick(observeArchiveTableWraps)
}, { flush: 'post' })

watch(
  () => activeCacheProcesses.value.map((item) => item.articleId).join(','),
  () => {
    activeProcessIndex.value = 0
  },
)

onMounted(() => {
  void loadArchiveAccounts()
  startCacheProcessRotation()
  if (typeof ResizeObserver !== 'undefined') {
    archiveTableResizeObserver = new ResizeObserver(updateArchiveTableRowHeights)
  }
  void nextTick(observeArchiveTableWraps)
})

onBeforeUnmount(() => {
  clearCachePolling()
  clearCacheProcessRotation()
  archiveTableResizeObserver?.disconnect()
})

</script>

<template>
  <section class="management-page files-page" aria-label="数据文件">
    <div class="metric-grid files-metrics config-summary-metrics">
      <article v-for="item in archiveMetrics" :key="item.label" class="metric-card page-panel">
        <span :class="['metric-icon', item.tone]">
          <AppIcon :icon="item.icon" />
        </span>
        <div class="metric-body">
          <span>{{ item.label }}</span>
          <strong :class="item.tone">{{ item.value }}</strong>
        </div>
      </article>

      <article class="cache-task-status-card metric-card page-panel" aria-live="polite">
        <span :class="['metric-icon', cacheTaskTone]">
          <AppIcon icon="fa-solid fa-download" />
        </span>
        <div class="cache-status-body">
          <div class="cache-status-head">
            <span>缓存任务</span>
            <strong :class="['cache-status-value', cacheTaskTone]">{{ cacheTaskStatusValue }}</strong>
          </div>
          <small :title="cacheTaskStatusSummary">{{ cacheTaskStatusSummary }}</small>
        </div>
      </article>

      <article
        class="cache-active-process-card metric-card page-panel"
        aria-live="polite"
        @mouseenter="pauseCacheProcessRotation"
        @mouseleave="resumeCacheProcessRotation"
      >
        <span class="metric-icon purple">
          <AppIcon icon="fa-solid fa-gears" />
        </span>
        <div class="cache-status-body">
          <div class="cache-status-head">
            <span>活跃子进程</span>
            <strong class="cache-status-value purple">
              {{ activeCacheProcesses.length }} / {{ cacheJobSnapshot?.concurrency || 0 }}
            </strong>
          </div>
          <Transition name="cache-process-slide" mode="out-in">
            <div
              :key="visibleActiveProcess?.articleId || 'cache-process-idle'"
              class="cache-process-content"
            >
              <span
                v-if="visibleActiveProcess"
                class="cache-process-title"
                :title="visibleActiveProcess.articleTitle"
              >
                {{ visibleActiveProcess.articleTitle }}
              </span>
              <small :title="cacheActiveProcessSummary">{{ cacheActiveProcessSummary }}</small>
            </div>
          </Transition>
        </div>
      </article>
    </div>

    <section class="file-list page-panel" aria-label="公众号列表">
      <div class="file-list-header">
        <h2 class="section-heading">
          <AppIcon icon="fa-regular fa-rectangle-list" />
          公众号列表
        </h2>

        <div class="filters-row file-filters">
          <VxeSelect
            v-model="selectedAccount"
            class="file-vxe-control account-select"
            clearable
            filterable
            placeholder="选择公众号"
            :options="accountSelectOptions"
            :option-props="{ label: 'label', value: 'value' }"
            :popup-config="{ transfer: true, zIndex: 3000, className: 'account-select-panel' }"
            aria-label="选择公众号"
          />
          <VxeDateRangePicker
            v-model:start-value="selectedCollectStartDate"
            v-model:end-value="selectedCollectEndDate"
            class="file-vxe-control file-date-range-picker"
            type="date"
            clearable
            auto-close
            placeholder="采集起始日期 ~ 采集结束日期"
            separator=" ~ "
            value-format="yyyy-MM-dd"
            label-format="yyyy-MM-dd"
            :popup-config="{ transfer: true, zIndex: 3000, className: 'file-date-range-picker-panel' }"
            aria-label="采集起始日期和采集结束日期"
          />
        </div>
      </div>

      <div ref="accountTableWrapRef" class="table-wrap">
        <table class="data-table account-table">
          <colgroup>
            <col class="account-index-col" />
            <col class="account-name-col" />
            <col class="account-time-col" />
            <col class="account-size-col" />
            <col class="account-action-col" />
          </colgroup>
          <thead>
            <tr>
              <th>序号</th>
              <th>公众号</th>
              <th>采集时间</th>
              <th>数量</th>
              <th class="action-cell">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="archiveAccountsLoading">
              <td class="table-state-cell" colspan="5">正在读取数据库中的公众号列表...</td>
            </tr>
            <tr v-else-if="archiveAccountsError">
              <td class="table-state-cell error" colspan="5">{{ archiveAccountsError }}</td>
            </tr>
            <tr v-else-if="visibleFileRows.length === 0">
              <td class="table-state-cell" colspan="5">数据库中暂无公众号记录</td>
            </tr>
            <template v-else>
              <tr v-for="(file, index) in visibleFileRows" :key="file.id">
                <td>{{ (fileCurrentPage - 1) * filePageSize + index + 1 }}</td>
                <td class="account-name-cell" :title="file.account">{{ truncateAccountName(file.account) }}</td>
                <td>{{ file.createdAt }}</td>
                <td>{{ file.articleCount }}</td>
                <td class="action-cell">
                  <span class="table-actions">
                    <button class="text-link" type="button" @click="previewFile(file)">预览</button>
                    <button
                      class="text-link"
                      type="button"
                      :disabled="archiveCaching"
                      @click="cacheAccountArticles(file)"
                    >
                      一键缓存
                    </button>
                    <button
                      class="text-link danger"
                      type="button"
                      :disabled="archiveDeleting || archiveCaching"
                      @click="openDeleteAccountDialog(file)"
                    >
                      删除
                    </button>
                  </span>
                </td>
              </tr>
              <tr
                v-for="placeholderIndex in filePlaceholderRowCount"
                :key="`account-placeholder-${placeholderIndex}`"
                class="table-placeholder-row"
                aria-hidden="true"
              >
                <td colspan="5"></td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>

      <div class="pagination-bar">
        <span class="account-pagination-total">共 {{ filePagerTotal }} 条</span>
        <VxePager
          v-model:current-page="fileCurrentPage"
          v-model:page-size="filePageSize"
          class-name="file-vxe-pager"
          size="mini"
          align="right"
          :layouts="pagerLayouts"
          :pager-count="7"
          :page-sizes="[10]"
          :total="filePagerTotal"
          @page-change="handleFilePageChange"
        >
          <template #right>
            <span class="fixed-page-size" aria-label="每页条数">{{ filePageSize }} 条/页</span>
          </template>
        </VxePager>
      </div>
    </section>

    <aside class="file-side">
      <section class="record-detail page-panel">
        <img class="panel-corner-art detail-art" src="/assets/watercolor-leaf-branch-a.png" alt="" />
        <div class="record-detail-header">
          <h2 class="section-heading">
            <AppIcon icon="fa-regular fa-file-lines" />
            记录详情
          </h2>

          <div v-if="selectedPreviewFile" class="record-actions" aria-label="记录详情操作">
            <div class="record-selection-summary" aria-live="polite">
              <span class="record-account-name">{{ selectedPreviewFile.account }}</span>
              <span>已选择 {{ selectedRecordCount }} 条</span>
            </div>
            <div class="record-action-buttons">
              <button
                class="action-button primary"
                type="button"
                :disabled="selectedRecordCount === 0 || archiveCaching || archiveArticlesLoading"
                @click="cacheSelectedRecords"
              >
                <AppIcon icon="fa-solid fa-download" />
                {{ archiveCaching ? '缓存中' : '缓存' }}
              </button>
              <button
                class="action-button danger"
                type="button"
                :disabled="selectedRecordCount === 0 || archiveDeleting || archiveCaching || archiveArticlesLoading"
                @click="openDeleteSelectedRecordsDialog"
              >
                <AppIcon icon="fa-regular fa-trash-can" />
                删除
              </button>
            </div>
          </div>
        </div>

        <template v-if="selectedPreviewFile">

          <div ref="recordTableWrapRef" class="table-wrap record-table-wrap">
            <table class="data-table record-table">
              <colgroup>
                <col class="record-action-col" />
                <col />
                <col class="record-time-col" />
                <col class="record-size-col" />
                <col class="record-open-col" />
              </colgroup>
              <thead>
                <tr>
                  <th class="checkbox-cell">
                    <input
                      class="record-checkbox"
                      type="checkbox"
                      :checked="isAllRecordsSelected"
                      :indeterminate.prop="isSomeRecordsSelected"
                      :disabled="recordPagerTotal === 0 || archiveArticlesLoading || Boolean(archiveArticlesError)"
                      aria-label="全选记录详情列表"
                      @change="toggleAllRecords"
                    />
                  </th>
                  <th>标题</th>
                  <th>文章发布时间</th>
                  <th>大小</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="archiveArticlesLoading">
                  <td class="table-state-cell" colspan="5">正在读取该公众号的记录详情...</td>
                </tr>
                <tr v-else-if="archiveArticlesError">
                  <td class="table-state-cell error" colspan="5">{{ archiveArticlesError }}</td>
                </tr>
                <tr v-else-if="visibleRecordRows.length === 0">
                  <td class="table-state-cell" colspan="5">该公众号暂无文章记录</td>
                </tr>
                <template v-else>
                  <tr v-for="(record, index) in visibleRecordRows" :key="record.id">
                    <td class="checkbox-cell">
                      <input
                        v-model="selectedRecordIndexes"
                        class="record-checkbox"
                        type="checkbox"
                        :value="(recordCurrentPage - 1) * recordPageSize + index"
                        :aria-label="`勾选第 ${index + 1} 条记录`"
                      />
                    </td>
                    <td class="record-title">
                      <button
                        class="record-title-link"
                        type="button"
                        :disabled="!record.link"
                        :title="record.link ? `${record.title}\n${record.link}` : record.title"
                        @click="openArticleLink(record)"
                      >
                        {{ record.title }}
                      </button>
                    </td>
                    <td class="record-time">{{ record.publishedAt }}</td>
                    <td class="record-size">{{ record.size }}</td>
                    <td class="record-open-cell">
                      <button
                        class="text-link"
                        type="button"
                        @click="openRecordArchiveDirectory(record)"
                      >
                        打开目录
                      </button>
                    </td>
                  </tr>
                  <tr
                    v-for="placeholderIndex in recordPlaceholderRowCount"
                    :key="`record-placeholder-${placeholderIndex}`"
                    class="table-placeholder-row"
                    aria-hidden="true"
                  >
                    <td colspan="5"></td>
                  </tr>
                </template>
              </tbody>
            </table>
          </div>

          <div class="record-pagination" aria-label="记录详情分页">
            <span class="record-pagination-total">共 {{ recordPagerTotal }} 条</span>
            <VxePager
              v-model:current-page="recordCurrentPage"
              v-model:page-size="recordPageSize"
              class-name="file-vxe-pager record-vxe-pager"
              size="mini"
              align="right"
              :layouts="pagerLayouts"
              :pager-count="5"
              :page-sizes="[10]"
              :total="recordPagerTotal"
              @page-change="handleRecordPageChange"
            >
              <template #right>
                <span class="fixed-page-size" aria-label="记录每页条数">{{ recordPageSize }} 条/页</span>
              </template>
            </VxePager>
          </div>
        </template>
        <div v-else class="record-empty" aria-live="polite">
          <strong>请先点击左侧“预览”</strong>
          <span>选择一个公众号后，这里会显示对应的记录详情列表、批量操作和分页按钮。</span>
        </div>
      </section>
    </aside>

    <section class="bottom-quick-actions page-panel" aria-label="快速操作">
      <div class="quick-actions-head">
        <h2 class="section-heading">
          <AppIcon icon="fa-solid fa-bolt" />
          快速操作
        </h2>
      </div>

      <div class="bottom-quick-grid">
        <button class="action-button ghost" type="button" @click="handleOpenStorageDirectory">
          <AppIcon icon="fa-regular fa-folder-open" />
          打开目录
        </button>
        <button
          class="action-button purple"
          type="button"
          :disabled="fileListRows.length === 0"
          @click="openBatchExportDialog"
        >
          <AppIcon icon="fa-regular fa-file-excel" />
          批量导出
        </button>
        <button
          class="action-button danger"
          type="button"
          :disabled="archiveDeleting || archiveCaching || fileListRows.length === 0"
          @click="openDeleteAllArchivesDialog"
        >
          <AppIcon icon="fa-regular fa-trash-can" />
          全部删除
        </button>
      </div>
    </section>

    <transition name="batch-export-dialog-fade">
      <div
        v-if="batchExportDialogOpen"
        class="batch-export-dialog-layer"
        role="presentation"
        @click.self="closeBatchExportDialog"
      >
        <section
          class="batch-export-dialog"
          role="dialog"
          aria-modal="true"
          aria-labelledby="batch-export-dialog-title"
        >
          <header class="batch-export-head">
            <span class="batch-export-icon" aria-hidden="true">
              <AppIcon icon="fa-regular fa-file-excel" />
            </span>
            <div>
              <h3 id="batch-export-dialog-title">已有公众号列表</h3>
              <p>选择需要导出的公众号，下一步将把对应记录写入 Excel 文件。</p>
            </div>
          </header>

          <div class="batch-export-meta" aria-live="polite">
            已选择 {{ selectedExportCount }} 个公众号，共 {{ selectedExportRecordCount }} 条记录
          </div>

          <div class="batch-export-table-wrap">
            <table class="data-table batch-export-table">
              <colgroup>
                <col class="export-check-col" />
                <col class="export-index-col" />
                <col />
                <col class="export-count-col" />
              </colgroup>
              <thead>
                <tr>
                  <th class="export-check-col">
                    <input
                      class="record-checkbox"
                      type="checkbox"
                      :checked="isAllExportAccountsSelected"
                      :indeterminate="isSomeExportAccountsSelected"
                      :disabled="archiveExporting"
                      aria-label="选择全部公众号"
                      @change="toggleAllExportAccounts"
                    />
                  </th>
                  <th>公众号</th>
                  <th>记录数</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="batchExportRows.length === 0">
                  <td class="table-state-cell" colspan="4">数据库中暂无公众号记录</td>
                </tr>
                <tr v-for="(file, index) in batchExportRows" :key="file.id">
                  <td class="export-check-cell">
                    <input
                      v-model="selectedExportAccountIds"
                      class="record-checkbox"
                      type="checkbox"
                      :value="file.id"
                      :disabled="archiveExporting"
                      :aria-label="`选择公众号 ${file.account}`"
                    />
                  </td>
                  <td class="export-index-cell">{{ index + 1 }}</td>
                  <td class="export-account-cell" :title="file.account">{{ file.account }}</td>
                  <td class="export-count-cell">{{ file.articleCount }} 条</td>
                </tr>
              </tbody>
            </table>
          </div>

          <footer class="batch-export-actions">
            <button class="action-button ghost" type="button" :disabled="archiveExporting" @click="closeBatchExportDialog">
              取消
            </button>
            <button
              class="action-button success"
              type="button"
              :disabled="selectedExportCount === 0 || archiveExporting"
              @click="handleBatchExportExcel"
            >
              <AppIcon :class="{ 'spin-icon': archiveExporting }" :icon="archiveExporting ? 'fa-solid fa-rotate' : 'fa-regular fa-file-excel'" />
              {{ archiveExporting ? '正在导出...' : '导出为excel' }}
            </button>
          </footer>
        </section>
      </div>
    </transition>

    <ConfirmDialog
      :open="deleteDialog.open"
      :title="deleteDialog.title"
      :description="deleteDialog.description"
      :summary-items="deleteDialog.summaryItems"
      :detail-title="deleteDialog.detailTitle"
      :detail-items="deleteDialog.detailItems"
      :warning="deleteDialog.warning"
      :error-message="deleteDialog.errorMessage"
      :loading="archiveDeleting"
      :confirm-text="deleteDialog.confirmText"
      tone="danger"
      icon="fa-regular fa-trash-can"
      confirm-icon="fa-regular fa-trash-can"
      loading-text="删除中..."
      @cancel="closeDeleteDialog"
      @confirm="confirmDeleteDialog"
    />

    <transition-group name="archive-toast-fade" tag="div" class="archive-toast-stack" aria-live="polite">
      <div
        v-for="toast in cacheToasts"
        :key="toast.id"
        :class="['archive-toast', `archive-toast--${toast.tone}`]"
        role="status"
      >
        {{ toast.message }}
      </div>
    </transition-group>
  </section>
</template>

<style scoped>
.files-page {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  grid-template-rows: 72px 548px 106px;
  grid-template-areas:
    'metrics metrics'
    'list side'
    'quick quick';
}

.files-metrics {
  grid-area: metrics;
}

.files-metrics .metric-card {
  min-height: 72px;
}

.files-metrics > .metric-card {
  height: 72px;
  min-width: 0;
  overflow: hidden;
}

.cache-status-body {
  display: grid;
  align-content: center;
  gap: 3px;
  min-width: 0;
  overflow: hidden;
}

.cache-status-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
}

.cache-status-head > span {
  overflow: hidden;
  color: var(--ink-strong);
  font-size: 14px;
  font-weight: 700;
  line-height: 1.15;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cache-status-value {
  flex: 0 0 auto;
  color: var(--blue);
  font-size: 14px;
  font-weight: 700;
  line-height: 1.15;
  white-space: nowrap;
}

.cache-status-value.green {
  color: var(--green);
}

.cache-status-value.purple {
  color: var(--purple);
}

.cache-status-value.orange {
  color: var(--orange);
}

.cache-status-value.red {
  color: #d9413f;
}

.cache-status-body small,
.cache-process-title {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cache-status-body small {
  color: var(--ink-muted);
  font-size: 11px;
  font-weight: 500;
  line-height: 1.2;
}

.cache-process-content {
  display: grid;
  gap: 1px;
  min-width: 0;
  overflow: hidden;
}

.cache-process-title {
  color: var(--ink);
  font-size: 12px;
  font-weight: 600;
  line-height: 1.2;
}

.cache-process-slide-enter-active,
.cache-process-slide-leave-active {
  transition: opacity 180ms ease, transform 180ms ease;
}

.cache-process-slide-enter-from {
  opacity: 0;
  transform: translateY(5px);
}

.cache-process-slide-leave-to {
  opacity: 0;
  transform: translateY(-5px);
}

.files-page .section-heading {
  font-weight: 500;
  letter-spacing: 0;
}

.file-list {
  grid-area: list;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  row-gap: 4px;
  min-height: 0;
  padding: 18px 20px;
}

.file-list-header {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  align-items: center;
  gap: 24px;
  min-height: 48px;
  min-width: 0;
}

.file-list-header .section-heading {
  margin: 0;
  white-space: nowrap;
}

.file-list,
.record-detail,
.bottom-quick-actions {
  box-shadow: var(--paper-shadow-sm), var(--paper-shadow-md);
}

.file-list .data-table th,
.record-table th {
  height: 34px;
}

.file-list .data-table td,
.record-table td {
  height: var(--paged-table-row-height, 34px);
}

.file-list .data-table th,
.file-list .data-table td {
  padding: 0 8px;
}

.files-page .data-table th {
  background: rgba(234, 244, 251, 0.48);
  font-weight: 500;
}

.files-page .data-table td {
  font-weight: 400;
}

.file-list .table-wrap {
  position: relative;
  z-index: 1;
  height: auto;
  align-self: stretch;
  min-height: 0;
  margin-top: 8px;
  overflow: hidden;
}

.account-table {
  table-layout: fixed;
}

.account-index-col {
  width: 46px;
}

.account-name-col {
  width: 22%;
}

.account-time-col {
  width: 26%;
}

.account-size-col {
  width: 9%;
}

.account-action-col {
  width: 220px;
}

.file-list .data-table th {
  text-align: center;
}

.file-list .data-table th.action-cell {
  text-align: center;
}

.file-list .data-table td:nth-child(1),
.file-list .data-table td:nth-child(2),
.file-list .data-table td:nth-child(3),
.file-list .data-table td:nth-child(4),
.file-list .data-table td.action-cell {
  text-align: center;
}

.account-table td:nth-child(2) {
  overflow: hidden;
  text-overflow: ellipsis;
}

.account-name-cell {
  max-width: 100%;
  overflow: hidden;
  white-space: nowrap;
}

.account-table .table-actions {
  display: inline-flex;
  align-items: center;
  flex-wrap: nowrap;
  gap: 6px;
  justify-content: center;
}

.account-table .text-link {
  min-width: 50px;
  padding: 0 6px;
  cursor: pointer;
  font-size: 13px;
  line-height: 1.2;
}

.account-table .text-link:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.file-list .data-table .table-state-cell,
.record-detail .data-table .table-state-cell {
  height: calc(var(--paged-table-row-height, 34px) * 10);
  color: var(--ink-muted);
  font-size: 13px;
  font-weight: 400;
  text-align: center;
}

.files-page .table-placeholder-row {
  pointer-events: none;
}

.files-page .table-placeholder-row td {
  padding: 0;
}

.file-list .data-table .table-state-cell.error,
.record-detail .data-table .table-state-cell.error {
  color: #c93e3a;
}

.file-side {
  grid-area: side;
  display: grid;
  grid-template-rows: 1fr;
  min-width: 0;
}

.record-detail,
.bottom-quick-actions {
  padding: 18px 24px;
}

.record-detail {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  row-gap: 4px;
  min-height: 0;
}

.bottom-quick-actions {
  padding: 12px 20px;
}

.detail-art {
  top: 0;
  right: 0;
  width: 116px;
}

.record-detail-header {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  align-items: center;
  gap: 24px;
  min-height: 48px;
  min-width: 0;
}

.record-detail-header .section-heading {
  margin: 0;
  white-space: nowrap;
}

.record-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  justify-self: end;
  gap: 10px;
  width: min(100%, 690px);
  min-width: 0;
  margin-top: 0;
}

.record-selection-summary {
  display: inline-flex;
  align-items: center;
  gap: 14px;
  flex: 1 1 auto;
  min-width: 0;
  min-height: 34px;
  padding: 0 12px;
  border: 1px solid var(--line-soft);
  border-radius: 8px;
  color: var(--ink);
  background: rgba(255, 255, 255, 0.36);
  box-shadow: var(--paper-shadow-sm);
  font-size: 13px;
  font-weight: 400;
  white-space: nowrap;
}

.record-account-name {
  color: var(--ink-strong);
  font-weight: 700;
}

.record-action-buttons {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  margin-left: auto;
}

.record-actions .action-button {
  min-width: 82px;
}

.record-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 462px;
  margin-top: 16px;
  padding: 24px;
  gap: 8px;
  border: 1px dashed rgba(104, 141, 181, 0.26);
  border-radius: 10px;
  color: var(--ink-muted);
  background: rgba(255, 255, 255, 0.26);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.48);
  text-align: center;
}

.record-empty strong {
  color: var(--ink-strong);
  font-size: 15px;
  font-weight: 500;
}

.record-empty span {
  max-width: 280px;
  font-size: 13px;
  font-weight: 400;
  line-height: 1.6;
}

.action-button.danger {
  color: #ffffff;
  border-color: rgba(217, 65, 63, 0.44);
  background:
    radial-gradient(circle at 20% 15%, rgba(255, 255, 255, 0.28), transparent 40%),
    linear-gradient(135deg, #e4635f, #c93e3a);
}

.record-table-wrap {
  height: auto;
  align-self: stretch;
  min-height: 0;
  margin-top: 8px;
  overflow: hidden;
}

.record-table {
  table-layout: fixed;
  font-size: 13px;
}

.record-table th,
.record-table td {
  padding: 0 9px;
}

.record-table th {
  z-index: 2;
  text-align: center;
}

.record-action-col {
  width: 58px;
}

.record-time-col {
  width: 142px;
}

.record-size-col {
  width: 76px;
}

.record-open-col {
  width: 86px;
}

.record-table .checkbox-cell,
.record-table .record-time,
.record-table .record-size,
.record-table .record-open-cell {
  text-align: center;
}

.record-title {
  color: var(--ink-strong);
}

.record-title-link {
  display: block;
  width: 100%;
  min-width: 0;
  padding: 0;
  border: 0;
  color: var(--blue);
  background: transparent;
  font: inherit;
  font-weight: 400;
  line-height: 1.2;
  text-align: left;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: pointer;
}

.record-title-link:hover:not(:disabled) {
  color: #1e5fae;
  text-decoration: none;
}

.record-title-link:disabled {
  color: var(--ink-strong);
  cursor: default;
}

.record-open-cell .text-link {
  padding: 0 1px;
  cursor: pointer;
  font-size: 13px;
  line-height: 1.2;
}

.account-table .text-link,
.record-open-cell .text-link {
  display: inline-grid;
  place-items: center;
  min-height: 26px;
  border-radius: 6px;
  background: rgba(45, 117, 214, 0.08);
  text-decoration: none;
  transition:
    background 150ms ease,
    color 150ms ease;
}

.account-table .table-actions .text-link {
  min-width: 50px;
  padding: 0 6px;
}

.file-list .pagination-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
  box-sizing: border-box;
  min-height: 40px;
  padding-top: 4px;
  padding-right: 0;
  padding-left: 0;
  margin-top: 0;
}

.account-pagination-total {
  flex: 0 0 auto;
  margin: 0;
  padding: 0;
  padding-left: 8px;
}

.file-list .pagination-bar :deep(.file-vxe-pager.vxe-pager) {
  flex: 0 0 auto;
  width: auto;
  min-width: 0;
  margin-left: auto;
}

.file-list .pagination-bar :deep(.file-vxe-pager .vxe-pager--wrapper) {
  width: auto;
}

.account-table .text-link:hover:not(:disabled),
.record-open-cell .text-link:hover:not(:disabled) {
  background: rgba(45, 117, 214, 0.14);
}

.account-table .text-link.danger,
.record-open-cell .text-link.danger {
  color: var(--red);
  background: rgba(217, 65, 63, 0.08);
}

.account-table .text-link.danger:hover:not(:disabled),
.record-open-cell .text-link.danger:hover:not(:disabled) {
  background: rgba(217, 65, 63, 0.13);
}

.record-open-cell .text-link:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.record-checkbox {
  width: 16px;
  height: 16px;
  accent-color: #2d70cc;
  cursor: pointer;
  vertical-align: middle;
}

.record-checkbox:disabled {
  cursor: not-allowed;
  opacity: 0.48;
}

.record-pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
  min-height: 40px;
  margin-top: 8px;
  color: var(--ink);
  font-size: 13px;
  font-weight: 900;
}

.record-pagination-total {
  flex: 0 0 auto;
  margin: 0;
  padding: 0;
  padding-left: 8px;
  font-weight: 400;
}

.file-list :deep(.file-vxe-pager.vxe-pager),
.record-detail :deep(.file-vxe-pager.vxe-pager) {
  flex: 1 1 auto;
  min-width: 0;
  margin-left: auto;
  padding: 0;
  color: var(--ink);
  background: transparent;
  font-size: 13px;
  font-weight: 900;
}

.record-detail :deep(.record-vxe-pager.vxe-pager) {
  flex: 0 0 auto;
  width: auto;
  margin-left: auto;
}

.record-detail :deep(.record-vxe-pager .vxe-pager--wrapper) {
  flex: 0 0 auto;
  width: auto;
}

.file-list :deep(.file-vxe-pager .vxe-pager--wrapper),
.record-detail :deep(.file-vxe-pager .vxe-pager--wrapper) {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
  width: 100%;
  min-height: 32px;
}

.file-list :deep(.file-vxe-pager .vxe-pager--prev-btn),
.file-list :deep(.file-vxe-pager .vxe-pager--next-btn),
.file-list :deep(.file-vxe-pager .vxe-pager--num-btn),
.file-list :deep(.file-vxe-pager .vxe-pager--jump-prev),
.file-list :deep(.file-vxe-pager .vxe-pager--jump-next),
.record-detail :deep(.file-vxe-pager .vxe-pager--prev-btn),
.record-detail :deep(.file-vxe-pager .vxe-pager--next-btn),
.record-detail :deep(.file-vxe-pager .vxe-pager--num-btn),
.record-detail :deep(.file-vxe-pager .vxe-pager--jump-prev),
.record-detail :deep(.file-vxe-pager .vxe-pager--jump-next) {
  display: inline-grid;
  place-items: center;
  min-width: 32px;
  height: 32px;
  padding: 0 9px;
  border: 1px solid transparent;
  border-radius: 6px;
  color: var(--blue);
  background: rgba(255, 255, 255, 0.64);
  box-shadow: none;
  font: inherit;
  line-height: 1;
  cursor: pointer;
  transition:
    border-color 150ms ease,
    background 150ms ease,
    color 150ms ease;
}

.file-list :deep(.file-vxe-pager .vxe-pager--prev-btn),
.file-list :deep(.file-vxe-pager .vxe-pager--next-btn),
.record-detail :deep(.file-vxe-pager .vxe-pager--prev-btn),
.record-detail :deep(.file-vxe-pager .vxe-pager--next-btn) {
  width: 32px;
  padding: 0;
  color: rgba(77, 108, 159, 0.78);
}

.file-list :deep(.file-vxe-pager .vxe-pager--jump-prev),
.file-list :deep(.file-vxe-pager .vxe-pager--jump-next),
.record-detail :deep(.file-vxe-pager .vxe-pager--jump-prev),
.record-detail :deep(.file-vxe-pager .vxe-pager--jump-next) {
  min-width: 24px;
  padding: 0 6px;
  color: rgba(77, 108, 159, 0.72);
}

.file-list :deep(.file-vxe-pager .vxe-pager--prev-btn:hover:not(.is--disabled)),
.file-list :deep(.file-vxe-pager .vxe-pager--next-btn:hover:not(.is--disabled)),
.file-list :deep(.file-vxe-pager .vxe-pager--num-btn:hover:not(.is--active)),
.file-list :deep(.file-vxe-pager .vxe-pager--jump-prev:hover:not(.is--disabled)),
.file-list :deep(.file-vxe-pager .vxe-pager--jump-next:hover:not(.is--disabled)),
.record-detail :deep(.file-vxe-pager .vxe-pager--prev-btn:hover:not(.is--disabled)),
.record-detail :deep(.file-vxe-pager .vxe-pager--next-btn:hover:not(.is--disabled)),
.record-detail :deep(.file-vxe-pager .vxe-pager--num-btn:hover:not(.is--active)),
.record-detail :deep(.file-vxe-pager .vxe-pager--jump-prev:hover:not(.is--disabled)),
.record-detail :deep(.file-vxe-pager .vxe-pager--jump-next:hover:not(.is--disabled)) {
  border-color: rgba(45, 117, 214, 0.24);
  background: rgba(255, 255, 255, 0.86);
}

.file-list :deep(.file-vxe-pager .vxe-pager--num-btn.is--active),
.record-detail :deep(.file-vxe-pager .vxe-pager--num-btn.is--active) {
  color: #ffffff;
  border-color: rgba(45, 117, 214, 0.32);
  background: linear-gradient(135deg, #4d85dc, #2d70cc);
}

.file-list :deep(.file-vxe-pager .is--disabled),
.record-detail :deep(.file-vxe-pager .is--disabled) {
  cursor: not-allowed;
  color: rgba(77, 108, 159, 0.36);
  background: rgba(255, 255, 255, 0.46);
}

.file-list :deep(.file-vxe-pager .vxe-pager--btn-icon),
.file-list :deep(.file-vxe-pager .vxe-pager--jump-icon),
.file-list :deep(.file-vxe-pager .vxe-pager--jump-more-icon),
.record-detail :deep(.file-vxe-pager .vxe-pager--btn-icon),
.record-detail :deep(.file-vxe-pager .vxe-pager--jump-icon),
.record-detail :deep(.file-vxe-pager .vxe-pager--jump-more-icon) {
  line-height: 1;
}

.file-list :deep(.file-vxe-pager .vxe-pager--right-wrapper),
.record-detail :deep(.file-vxe-pager .vxe-pager--right-wrapper) {
  display: inline-flex;
  align-items: center;
  margin-left: 2px;
}

.fixed-page-size {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 82px;
  height: 30px;
  border: 1px solid var(--line);
  border-radius: 7px;
  color: var(--ink);
  background: rgba(255, 255, 255, 0.46);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.62);
  font-size: 13px;
  font-weight: 400;
  white-space: nowrap;
}

.bottom-quick-actions {
  grid-area: quick;
}

.quick-actions-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
}

.bottom-quick-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
  margin-top: 10px;
}

.bottom-quick-grid .action-button {
  width: 100%;
  height: 40px;
  font-size: 15px;
  color: #15386f;
  border-color: rgba(96, 137, 178, 0.22);
  background: rgba(255, 255, 255, 0.5);
  box-shadow: var(--paper-shadow-sm);
  font-weight: 500;
}

.bottom-quick-grid .action-button:hover:not(:disabled) {
  color: #12376d;
  border-color: rgba(45, 117, 214, 0.28);
  background: rgba(234, 244, 251, 0.68);
  box-shadow: var(--paper-shadow-sm);
  transform: none;
}

.bottom-quick-grid .action-button:active:not(:disabled) {
  transform: none;
  background: rgba(222, 237, 248, 0.72);
}

.bottom-quick-grid .action-button.purple {
  color: #5c4eb5;
  border-color: rgba(111, 100, 214, 0.22);
  background: rgba(246, 244, 255, 0.78);
}

.bottom-quick-grid .action-button.danger {
  color: #b4232e;
  border-color: rgba(217, 65, 63, 0.24);
  background: rgba(255, 241, 241, 0.76);
}

.bottom-quick-grid .action-button:disabled {
  box-shadow: var(--paper-shadow-sm);
  transform: none;
}

.batch-export-dialog-layer {
  position: fixed;
  inset: 0;
  z-index: 88;
  display: grid;
  place-items: center;
  padding: 28px;
  background: rgba(14, 31, 55, 0.28);
}

.batch-export-dialog {
  width: min(680px, calc(100vw - 56px));
  max-height: min(640px, calc(100vh - 56px));
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  border: 1px solid rgba(104, 141, 181, 0.28);
  border-radius: 8px;
  background: #fbfdff;
  box-shadow: 0 12px 16px rgba(23, 52, 86, 0.18);
  overflow: hidden;
}

.batch-export-head {
  display: grid;
  grid-template-columns: 42px minmax(0, 1fr);
  gap: 12px;
  align-items: center;
  padding: 18px 20px 16px;
  border-bottom: 1px solid rgba(104, 141, 181, 0.18);
  background: linear-gradient(180deg, rgba(244, 249, 253, 0.96), rgba(251, 253, 255, 0.96));
}

.batch-export-icon {
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  border: 1px solid rgba(31, 143, 105, 0.2);
  border-radius: 8px;
  color: #1f8f69;
  background: rgba(31, 143, 105, 0.12);
  font-size: 16px;
}

.batch-export-head h3 {
  margin: 0;
  color: var(--ink-strong);
  font-size: 18px;
  font-weight: 900;
  line-height: 1.2;
}

.batch-export-head p {
  margin: 6px 0 0;
  color: var(--ink-muted);
  font-size: 13px;
  font-weight: 800;
  line-height: 1.45;
}

.batch-export-meta {
  margin: 14px 20px 0;
  color: var(--ink-muted);
  font-size: 13px;
  font-weight: 900;
  line-height: 1.35;
}

.batch-export-table-wrap {
  min-height: 220px;
  max-height: 380px;
  margin: 10px 20px 16px;
  border: 1px solid var(--line-soft);
  border-radius: 7px;
  overflow: auto;
}

.file-list .table-wrap,
.record-table-wrap,
.batch-export-table-wrap {
  border: 1px solid rgba(104, 141, 181, 0.18);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.38);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.58);
}

.batch-export-table {
  table-layout: fixed;
}

.batch-export-table th,
.batch-export-table td {
  height: 40px;
  padding: 0 12px;
}

.batch-export-table th {
  position: sticky;
  top: 0;
  z-index: 1;
  text-align: center;
}

.batch-export-table .table-state-cell {
  height: 160px;
  color: var(--ink-muted);
  text-align: center;
  font-size: 13px;
  font-weight: 900;
}

.export-check-col {
  width: 54px;
}

.export-index-col {
  width: 72px;
}

.export-count-col {
  width: 116px;
}

.export-check-cell,
.export-index-cell,
.export-count-cell {
  text-align: center;
}

.export-account-cell {
  overflow: hidden;
  color: var(--ink-strong);
  font-weight: 900;
  text-overflow: ellipsis;
}

.batch-export-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  padding: 14px 20px 18px;
  border-top: 1px solid rgba(104, 141, 181, 0.18);
  background: rgba(244, 249, 253, 0.72);
}

.batch-export-actions .action-button {
  min-width: 104px;
}

.spin-icon {
  animation: archive-export-spin 900ms linear infinite;
}

@keyframes archive-export-spin {
  to {
    transform: rotate(360deg);
  }
}

.batch-export-dialog-fade-enter-active,
.batch-export-dialog-fade-leave-active {
  transition: opacity 160ms ease;
}

.batch-export-dialog-fade-enter-active .batch-export-dialog,
.batch-export-dialog-fade-leave-active .batch-export-dialog {
  transition: transform 160ms ease;
}

.batch-export-dialog-fade-enter-from,
.batch-export-dialog-fade-leave-to {
  opacity: 0;
}

.batch-export-dialog-fade-enter-from .batch-export-dialog,
.batch-export-dialog-fade-leave-to .batch-export-dialog {
  transform: translateY(8px);
}

.archive-toast-stack {
  position: fixed;
  right: 24px;
  bottom: 24px;
  z-index: 82;
  display: grid;
  gap: 8px;
  width: min(360px, calc(100vw - 48px));
  pointer-events: none;
}

.archive-toast {
  display: inline-flex;
  align-items: center;
  min-height: 38px;
  padding: 0 14px;
  border: 1px solid rgba(104, 141, 181, 0.24);
  border-radius: 8px;
  color: var(--ink-strong);
  background: rgba(251, 253, 255, 0.94);
  box-shadow: 0 8px 18px rgba(35, 69, 111, 0.14);
  font-size: 13px;
  font-weight: 900;
  line-height: 1.35;
  text-align: left;
}

.archive-toast--success {
  color: #0f684f;
  border-color: rgba(31, 143, 105, 0.24);
  background: rgba(223, 243, 232, 0.96);
}

.archive-toast--warning {
  color: #9a5415;
  border-color: rgba(223, 122, 53, 0.28);
  background: rgba(250, 235, 218, 0.96);
}

.archive-toast--error {
  color: #a93634;
  border-color: rgba(217, 65, 63, 0.28);
  background: rgba(253, 226, 224, 0.96);
}

.archive-toast-fade-enter-active,
.archive-toast-fade-leave-active {
  transition:
    opacity 160ms ease,
    transform 160ms ease;
}

.archive-toast-fade-enter-from,
.archive-toast-fade-leave-to {
  opacity: 0;
  transform: translateY(8px);
}

@media (prefers-reduced-motion: reduce) {
  .cache-process-slide-enter-active,
  .cache-process-slide-leave-active {
    transition: opacity 80ms ease;
  }

  .cache-process-slide-enter-from,
  .cache-process-slide-leave-to {
    transform: none;
  }

  .batch-export-dialog-fade-enter-active,
  .batch-export-dialog-fade-leave-active,
  .batch-export-dialog-fade-enter-active .batch-export-dialog,
  .batch-export-dialog-fade-leave-active .batch-export-dialog {
    transition: opacity 80ms ease;
  }

  .batch-export-dialog-fade-enter-from .batch-export-dialog,
  .batch-export-dialog-fade-leave-to .batch-export-dialog {
    transform: none;
  }

  .archive-toast-fade-enter-active,
  .archive-toast-fade-leave-active {
    transition: opacity 80ms ease;
  }

  .archive-toast-fade-enter-from,
  .archive-toast-fade-leave-to {
    transform: none;
  }

  .spin-icon {
    animation: none;
  }
}

.data-table td i {
  width: 22px;
  color: var(--green);
}

.file-filters {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 2fr);
  justify-self: end;
  position: relative;
  z-index: 8;
  width: min(100%, 600px);
  gap: 10px;
  margin-top: 0;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}

.file-vxe-control {
  width: 100%;
  min-width: 0;
}

.file-list :deep(.file-vxe-control.vxe-input),
.file-list :deep(.file-vxe-control.vxe-select),
.file-list :deep(.file-vxe-control.vxe-date-picker),
.file-list :deep(.file-vxe-control.vxe-date-range-picker) {
  width: 100%;
  height: 38px;
  color: var(--ink);
  font-size: 14px;
  font-weight: 400;
}

.file-list :deep(.file-vxe-control .vxe-input--wrapper) {
  border-color: var(--line);
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.48);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.6);
}

.file-list :deep(.file-vxe-control .vxe-input--inner),
.file-list :deep(.file-vxe-control .vxe-date-picker--inner),
.file-list :deep(.file-vxe-control .vxe-date-range-picker--inner) {
  color: var(--ink);
  font-size: 14px;
  font-weight: 400;
}

.file-list :deep(.file-vxe-control .vxe-input--inner::placeholder),
.file-list :deep(.file-vxe-control .vxe-date-picker--inner::placeholder),
.file-list :deep(.file-vxe-control .vxe-date-range-picker--inner::placeholder) {
  color: rgba(77, 108, 159, 0.72);
  font-weight: 400;
}

.file-list :deep(.file-date-picker.vxe-date-picker),
.file-list :deep(.file-date-range-picker.vxe-date-range-picker) {
  border-color: var(--line);
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.48);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.6);
}

.file-list :deep(.file-date-picker .vxe-date-picker--prefix),
.file-list :deep(.file-date-picker .vxe-date-picker--suffix),
.file-list :deep(.file-date-picker .vxe-date-picker--inner),
.file-list :deep(.file-date-range-picker .vxe-date-range-picker--prefix),
.file-list :deep(.file-date-range-picker .vxe-date-range-picker--suffix),
.file-list :deep(.file-date-range-picker .vxe-date-range-picker--inner) {
  background: transparent;
}

.file-list :deep(.file-date-range-picker .vxe-date-range-picker--inner) {
  text-align: center;
}

.file-list :deep(.file-date-range-picker .vxe-date-range-picker--inner::placeholder) {
  text-align: center;
}

:global(.file-date-picker-panel.vxe-date-picker--panel),
:global(.file-date-range-picker-panel.vxe-date-range-picker--panel) {
  color: var(--ink);
  font-size: 14px;
  font-weight: 400;
}

:global(.file-date-picker-panel .vxe-date-panel),
:global(.file-date-range-picker-panel .vxe-date-panel) {
  color: var(--ink);
  font-family: 'Microsoft YaHei', 'PingFang SC', 'Segoe UI', system-ui, sans-serif;
  font-size: 14px;
  font-weight: 400;
}

:global(.file-date-picker-panel .vxe-date-panel--picker-label),
:global(.file-date-picker-panel .vxe-date-panel--picker-btn),
:global(.file-date-picker-panel .vxe-date-panel--view-header),
:global(.file-date-picker-panel .vxe-date-panel--view-item-inner),
:global(.file-date-picker-panel .vxe-date-panel--label),
:global(.file-date-range-picker-panel .vxe-date-panel--picker-label),
:global(.file-date-range-picker-panel .vxe-date-panel--picker-btn),
:global(.file-date-range-picker-panel .vxe-date-panel--view-header),
:global(.file-date-range-picker-panel .vxe-date-panel--view-item-inner),
:global(.file-date-range-picker-panel .vxe-date-panel--label) {
  color: var(--ink);
  font-weight: 400;
}

:global(.file-date-picker-panel .vxe-date-panel--picker-type-wrapper),
:global(.file-date-picker-panel .vxe-date-panel--picker-label),
:global(.file-date-range-picker-panel .vxe-date-panel--picker-type-wrapper),
:global(.file-date-range-picker-panel .vxe-date-panel--picker-label) {
  color: var(--ink-strong);
  font-weight: 500;
}

:global(.file-date-picker-panel .vxe-date-panel--view-item.is--prev .vxe-date-panel--view-item-inner),
:global(.file-date-picker-panel .vxe-date-panel--view-item.is--next .vxe-date-panel--view-item-inner),
:global(.file-date-picker-panel .vxe-date-panel--view-item.is--prev .vxe-date-panel--label),
:global(.file-date-picker-panel .vxe-date-panel--view-item.is--next .vxe-date-panel--label),
:global(.file-date-range-picker-panel .vxe-date-panel--view-item.is--prev .vxe-date-panel--view-item-inner),
:global(.file-date-range-picker-panel .vxe-date-panel--view-item.is--next .vxe-date-panel--view-item-inner),
:global(.file-date-range-picker-panel .vxe-date-panel--view-item.is--prev .vxe-date-panel--label),
:global(.file-date-range-picker-panel .vxe-date-panel--view-item.is--next .vxe-date-panel--label) {
  color: rgba(77, 108, 159, 0.56);
  font-weight: 400;
}

:global(.account-select-panel.vxe-select--panel) {
  color: var(--ink);
  font-size: 14px;
  font-weight: 400;
}

:global(.account-select-panel .vxe-select--panel-wrapper) {
  border-color: var(--line);
  border-radius: 7px;
  background: #fbfdff;
  box-shadow: 0 12px 22px rgba(35, 69, 111, 0.14);
}

:global(.account-select-panel .vxe-select-option),
:global(.account-select-panel .vxe-select--empty-placeholder) {
  min-height: 32px;
  color: var(--ink);
  font-weight: 400;
}

:global(.account-select-panel .vxe-select-option.is--selected) {
  color: #1f8f69;
  font-weight: 500;
}

:global(.account-select-panel .vxe-select-search--input .vxe-input--inner) {
  color: var(--ink);
  font-weight: 400;
}

.file-date-picker,
.file-date-range-picker {
  min-width: 0;
}

:global(.collector-app.dark) .record-selection-summary,
:global(.collector-app.dark) .record-pagination,
:global(.collector-app.dark) .fixed-page-size {
  color: #b9c8dd;
}

:global(.collector-app.dark) .file-filters {
  border: 0;
  background: transparent;
  box-shadow: none;
}

:global(.collector-app.dark) .file-list .table-wrap,
:global(.collector-app.dark) .record-table-wrap,
:global(.collector-app.dark) .batch-export-table-wrap {
  border-color: rgba(128, 153, 188, 0.18);
  background: rgba(15, 24, 39, 0.52);
  box-shadow: inset 0 1px 0 rgba(214, 226, 244, 0.045);
}

:global(.collector-app.dark) .record-selection-summary {
  border-color: rgba(128, 153, 188, 0.18);
  background: rgba(15, 24, 39, 0.44);
}

:global(.collector-app.dark) .record-empty {
  border-color: rgba(128, 153, 188, 0.2);
  color: #8ea2bd;
  background: rgba(15, 24, 39, 0.36);
  box-shadow: inset 0 1px 0 rgba(214, 226, 244, 0.045);
}

:global(.collector-app.dark) .record-empty strong {
  color: #dce7f5;
}

:global(.collector-app.dark) .record-title-link {
  color: #8fbded;
}

:global(.collector-app.dark) .record-title-link:hover:not(:disabled) {
  color: #b8d7f8;
}

:global(.collector-app.dark) .record-title-link:disabled {
  color: #dce7f5;
}

:global(.collector-app.dark) .action-button.danger {
  border-color: rgba(181, 83, 84, 0.34);
  background: linear-gradient(180deg, rgba(132, 82, 80, 0.82), rgba(105, 64, 70, 0.8));
}

:global(.collector-app.dark) .file-list :deep(.file-vxe-control .vxe-input--wrapper),
:global(.collector-app.dark) .file-list :deep(.file-vxe-control.vxe-select),
:global(.collector-app.dark) .file-list :deep(.file-date-picker.vxe-date-picker),
:global(.collector-app.dark) .file-list :deep(.file-date-range-picker.vxe-date-range-picker) {
  border-color: rgba(128, 153, 188, 0.2);
  background: rgba(15, 24, 39, 0.62);
  box-shadow: inset 0 1px 0 rgba(214, 226, 244, 0.045);
}

:global(.collector-app.dark) .file-list :deep(.file-vxe-control .vxe-input--inner),
:global(.collector-app.dark) .file-list :deep(.file-vxe-control .vxe-date-picker--inner),
:global(.collector-app.dark) .file-list :deep(.file-vxe-control .vxe-date-range-picker--inner),
:global(.collector-app.dark) .file-list :deep(.file-date-picker .vxe-date-picker--prefix),
:global(.collector-app.dark) .file-list :deep(.file-date-picker .vxe-date-picker--suffix),
:global(.collector-app.dark) .file-list :deep(.file-date-range-picker .vxe-date-range-picker--prefix),
:global(.collector-app.dark) .file-list :deep(.file-date-range-picker .vxe-date-range-picker--suffix) {
  color: #cbd8ea;
}

:global(.collector-app.dark) .file-list :deep(.file-vxe-control .vxe-input--inner::placeholder),
:global(.collector-app.dark) .file-list :deep(.file-vxe-control .vxe-date-picker--inner::placeholder),
:global(.collector-app.dark) .file-list :deep(.file-vxe-control .vxe-date-range-picker--inner::placeholder) {
  color: rgba(142, 162, 189, 0.72);
}

:global(.collector-app.dark) .file-list :deep(.file-vxe-pager .vxe-pager--prev-btn),
:global(.collector-app.dark) .file-list :deep(.file-vxe-pager .vxe-pager--next-btn),
:global(.collector-app.dark) .file-list :deep(.file-vxe-pager .vxe-pager--num-btn),
:global(.collector-app.dark) .file-list :deep(.file-vxe-pager .vxe-pager--jump-prev),
:global(.collector-app.dark) .file-list :deep(.file-vxe-pager .vxe-pager--jump-next),
:global(.collector-app.dark) .record-detail :deep(.file-vxe-pager .vxe-pager--prev-btn),
:global(.collector-app.dark) .record-detail :deep(.file-vxe-pager .vxe-pager--next-btn),
:global(.collector-app.dark) .record-detail :deep(.file-vxe-pager .vxe-pager--num-btn),
:global(.collector-app.dark) .record-detail :deep(.file-vxe-pager .vxe-pager--jump-prev),
:global(.collector-app.dark) .record-detail :deep(.file-vxe-pager .vxe-pager--jump-next),
:global(.collector-app.dark) .fixed-page-size {
  color: #a9bfda;
  border-color: rgba(128, 153, 188, 0.16);
  background: rgba(17, 27, 44, 0.72);
  box-shadow: inset 0 1px 0 rgba(214, 226, 244, 0.04);
}

:global(.collector-app.dark) .file-list :deep(.file-vxe-pager .vxe-pager--prev-btn:hover:not(.is--disabled)),
:global(.collector-app.dark) .file-list :deep(.file-vxe-pager .vxe-pager--next-btn:hover:not(.is--disabled)),
:global(.collector-app.dark) .file-list :deep(.file-vxe-pager .vxe-pager--num-btn:hover:not(.is--active)),
:global(.collector-app.dark) .file-list :deep(.file-vxe-pager .vxe-pager--jump-prev:hover:not(.is--disabled)),
:global(.collector-app.dark) .file-list :deep(.file-vxe-pager .vxe-pager--jump-next:hover:not(.is--disabled)),
:global(.collector-app.dark) .record-detail :deep(.file-vxe-pager .vxe-pager--prev-btn:hover:not(.is--disabled)),
:global(.collector-app.dark) .record-detail :deep(.file-vxe-pager .vxe-pager--next-btn:hover:not(.is--disabled)),
:global(.collector-app.dark) .record-detail :deep(.file-vxe-pager .vxe-pager--num-btn:hover:not(.is--active)),
:global(.collector-app.dark) .record-detail :deep(.file-vxe-pager .vxe-pager--jump-prev:hover:not(.is--disabled)),
:global(.collector-app.dark) .record-detail :deep(.file-vxe-pager .vxe-pager--jump-next:hover:not(.is--disabled)) {
  color: #dceaff;
  border-color: rgba(111, 154, 211, 0.34);
  background: rgba(24, 38, 60, 0.86);
}

:global(.collector-app.dark) .file-list :deep(.file-vxe-pager .vxe-pager--num-btn.is--active),
:global(.collector-app.dark) .record-detail :deep(.file-vxe-pager .vxe-pager--num-btn.is--active) {
  color: #f0f6ff;
  border-color: rgba(111, 154, 211, 0.36);
  background: linear-gradient(180deg, #376fb0, #285c9c);
}

:global(.collector-app.dark) .file-list :deep(.file-vxe-pager .is--disabled),
:global(.collector-app.dark) .record-detail :deep(.file-vxe-pager .is--disabled) {
  color: rgba(142, 162, 189, 0.42);
  background: rgba(17, 27, 44, 0.42);
}

:global(.collector-app.dark) .batch-export-dialog-layer {
  background: rgba(7, 12, 22, 0.58);
}

:global(.collector-app.dark) .batch-export-dialog {
  border-color: rgba(98, 141, 196, 0.3);
  background: #141f31;
  box-shadow: 0 18px 34px rgba(0, 0, 0, 0.34);
}

:global(.collector-app.dark) .batch-export-head,
:global(.collector-app.dark) .batch-export-actions {
  border-color: rgba(128, 153, 188, 0.14);
  background: rgba(18, 28, 45, 0.94);
}

:global(.collector-app.dark) .batch-export-table-wrap {
  border-color: rgba(128, 153, 188, 0.14);
  background: rgba(13, 21, 34, 0.46);
}

:global(.collector-app.dark) .batch-export-icon {
  color: #83c7a8;
  border-color: rgba(64, 142, 111, 0.24);
  background: rgba(64, 142, 111, 0.14);
}

:global(.collector-app.dark) .batch-export-head h3,
:global(.collector-app.dark) .export-account-cell {
  color: #dce7f5;
}

:global(.collector-app.dark) .batch-export-head p,
:global(.collector-app.dark) .batch-export-meta,
:global(.collector-app.dark) .batch-export-table .table-state-cell {
  color: #8ea2bd;
}
</style>
