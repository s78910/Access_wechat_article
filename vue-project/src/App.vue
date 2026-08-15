<script setup lang="ts">
import AppIcon from './components/AppIcon.vue'
import { theme } from 'ant-design-vue'
import type { ThemeConfig } from 'ant-design-vue/es/config-provider/context'
import zhCN from 'ant-design-vue/es/locale/zh_CN'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { DynamicScroller, DynamicScrollerItem, type DynamicScrollerExposed } from 'vue-virtual-scroller'
import 'vue-virtual-scroller/dist/vue-virtual-scroller.css'
import AppTopbar from './components/AppTopbar.vue'
import TopbarHealthDialog from './components/TopbarHealthDialog.vue'
import TrafficSparkline from './components/TrafficSparkline.vue'
import DataFilesPage from './pages/DataFilesPage.vue'
import HistoryPage from './pages/HistoryPage.vue'
import SettingsPage from './pages/SettingsPage.vue'
import {
  getPythonStatus,
  getTaskLogs,
  getTaskStatus,
  checkHealthTarget,
  getStartupSelfCheckStatus,
  listArchiveSummary,
  openRuntimePath,
  runStartupHealthChecks,
  runStartupSelfCheck,
  startTask,
  stopTask,
  type ArchiveSummary,
  type HealthCheckResult,
  type StartupSelfCheckResult,
  type TaskLogItem,
  type TaskRuntimeState,
  type TaskRunOptions,
  type TaskStatus,
  type TrafficStatus,
} from './bridge/pythonApi'
import {
  getBrowserPreviewEnvironmentStatus,
  getEnvironmentErrorStatus,
  INITIAL_ENVIRONMENT_STATUS,
  resolvePywebviewEnvironmentStatus,
  type ResolvedPywebviewEnvironmentStatus,
} from './utils/pywebviewStatus'
import { formatLogMessageSegments, type LogMessageSegment } from './utils/logMessage'
import {
  canResumeLogAutoFollow,
  isLogScrollNearBottom,
  LOG_AUTO_FOLLOW_IDLE_MS,
  readLogScrollMetricsFromEvent,
} from './utils/logScroll'
import { buildArchiveSummaryStats } from './utils/archiveSummaryStats'
import { resolveTaskProgressSummary } from './utils/taskProgress'

type Tone = 'blue' | 'green' | 'red' | 'purple' | 'orange'
type TopbarHealthTone = 'success' | 'warning' | 'danger' | 'info'
type HealthCheckTarget = 'https' | 'ca' | 'proxy-port' | 'storage'
type TopbarHealthState = {
  value: string
  statusIcon: string
  tone: TopbarHealthTone
  message: string
  items: HealthCheckResult['items']
  checkedAt: string
  checking: boolean
}
type PageKey = 'home' | 'files' | 'history' | 'settings'
type NavItem = {
  label: string
  icon: string
  page: PageKey | null
  href?: string
}
type RuntimeLogLevel = 'INFO' | 'SUCCESS' | 'WARN' | 'ERROR'
type LogFilterLevel = 'ALL' | RuntimeLogLevel
type TaskDateFilterMode = 'all' | 'range' | 'before' | 'after'
type TaskDateRangeValue = [string, string] | null
type LogDisplayRow = {
  id: string
  time: string
  level: RuntimeLogLevel
  levelLabel: string
  levelClass: string
  message: string
  messageSegments: LogMessageSegment[]
  source: string
}

const isDark = ref(false)
const antThemeConfig = computed<ThemeConfig>(() => ({
  algorithm: isDark.value ? theme.darkAlgorithm : theme.defaultAlgorithm,
  token: {
    colorPrimary: '#357fd9',
    borderRadius: 8,
    controlHeight: 32,
    fontFamily: "'HarmonyOS Sans SC', 'Microsoft YaHei', sans-serif",
  },
}))
const activePage = ref<PageKey>('home')
const logScrollerRef = ref<DynamicScrollerExposed<LogDisplayRow> | null>(null)
const shouldStickLogToBottom = ref(true)
const lastLogScrollUserInteractionAt = ref(0)
const githubUrl = 'https://github.com/yeximm/Access_wechat_article'
const quickStartUrl = 'https://github.com/yeximm/Access_wechat_article/blob/main/doc/quick_start.md'
const MAX_PYWEBVIEW_STATUS_RETRIES = 12
const PYWEBVIEW_STATUS_RETRY_DELAY_MS = 400
const LOG_POLL_LIMIT = 100
const pageCount = ref(1)
const taskDateFilterMode = ref<TaskDateFilterMode>('all')
const taskStartDate = ref('')
const taskEndDate = ref('')
const taskDateRangeValue = computed<TaskDateRangeValue>({
  get: () => {
    if (!taskStartDate.value || !taskEndDate.value) {
      return null
    }
    return [taskStartDate.value, taskEndDate.value] as [string, string]
  },
  set: (value: TaskDateRangeValue) => {
    // Ant Design 范围选择器使用数组，页面内部继续保留独立的起止日期字符串。
    taskStartDate.value = value?.[0] ?? ''
    taskEndDate.value = value?.[1] ?? ''
  },
})
const taskDateFilterOptions: { label: string; value: TaskDateFilterMode }[] = [
  { label: '不限日期', value: 'all' },
  { label: '日期范围', value: 'range' },
  { label: '截止日期', value: 'before' },
  { label: '起始日期', value: 'after' },
]
const taskDateFilterLabel = computed(() =>
  taskDateFilterOptions.find((option) => option.value === taskDateFilterMode.value)?.label ?? '不限日期',
)
const pywebviewStatusLabel = ref('检测中')
const environmentStatus = ref({ ...INITIAL_ENVIRONMENT_STATUS })
const defaultTrafficStatus: TrafficStatus = {
  uploadBytesPerSecond: 0,
  downloadBytesPerSecond: 0,
  uploadLabel: '0 KB/s',
  downloadLabel: '0 KB/s',
  windowSeconds: 5,
  history: [],
}
const defaultRuntimeState: TaskRuntimeState = {
  currentAction: '点击开始运行后，将从桌面主页窗口读取',
  accountName: '等待识别',
  taskInfo: '待获取',
  proxyStatusLabel: '空闲',
  progressDone: 0,
  progressTotalLabel: '全部',
  progressPercent: 0,
  averageArticleSeconds: null,
  averageArticleDurationLabel: '待统计',
  activeWorkerCount: 0,
  totalWorkerCount: 0,
  errorCount: 0,
  latestError: '',
  articleRecords: [],
}
const taskStatus = ref<TaskStatus>({
  ok: false,
  status: 'idle',
  proxy: { host: '127.0.0.1', port: 18000, enabled: false },
  traffic: defaultTrafficStatus,
  runtimeState: defaultRuntimeState,
  workers: [],
  home: {
    status: 'pending',
    statusLabel: '待准备',
    accountName: '等待识别，请先打开微信 PC 端公众号主页',
    description: '点击开始运行后，将从桌面主页窗口读取',
    originalCount: '待获取',
    friendFollowCount: '待获取',
    found: false,
  },
})
const taskLogs = ref<TaskLogItem[]>([])
const frontendRuntimeLogs = ref<TaskLogItem[]>([])
const archiveSummary = ref<ArchiveSummary | null>(null)
const activeLogLevel = ref<LogFilterLevel>('ALL')
const uptimeSeconds = ref(0)
const homeRuntimeState = ref<'idle' | 'detecting' | 'running'>('idle')
const descriptionTooltip = ref({
  visible: false,
  text: '',
  x: 0,
  y: 0,
})
const downloadSelections = ref({
  articleDetail: true,
  offlineArchive: false,
  commentInfo: true,
  skipCollectedRecords: true,
})
const mainTaskSelectionDefaultsApplied = ref(false)
const isHoldingPageStep = ref(false)
let pageHoldDelayTimer: number | undefined
let pageHoldIntervalTimer: number | undefined
let pywebviewStatusRetryTimer: number | undefined
let pywebviewStatusRetryCount = 0
let taskPollingTimer: number | undefined
let uptimeTimer: number | undefined
let logAutoFollowTimer: number | undefined
let taskActionVersion = 0
let startupHealthCheckRequested = false
let startupSelfCheckRequested = false

// 静态数据先用于还原可视化原型，后续接入 Python 后端后替换为真实运行状态。
const navGroups: { title: string; items: NavItem[] }[] = [
  {
    title: '数据采集',
    items: [
      { label: '主服务', icon: 'fa-solid fa-house', page: 'home' },
      { label: '快速开始', icon: 'fa-solid fa-book-open', page: null, href: quickStartUrl },
    ],
  },
  {
    title: '系统管理',
    items: [
      { label: '数据档案', icon: 'fa-regular fa-folder-open', page: 'files' },
      { label: '采集历史', icon: 'fa-regular fa-clock', page: 'history' },
      { label: '系统配置', icon: 'fa-solid fa-gear', page: 'settings' },
    ],
  },
]

const homeSnapshot = computed(() => taskStatus.value.home ?? {
  status: 'pending',
  statusLabel: '待准备',
  accountName: '等待识别，请先打开微信 PC 端公众号主页',
  description: '点击开始运行后，将从桌面主页窗口读取',
  originalCount: '待获取',
  friendFollowCount: '待获取',
  found: false,
})

const normalizedPageCount = computed(() => {
  const count = Number(pageCount.value)
  return Number.isFinite(count) ? Math.max(0, Math.floor(count)) : 1
})

const taskDateFieldLabel = computed(() => {
  const labels: Record<TaskDateFilterMode, string> = {
    all: '日期范围',
    range: '日期范围',
    before: '截止日期',
    after: '起始日期',
  }

  return labels[taskDateFilterMode.value]
})

function selectTaskDateFilterMode(mode: TaskDateFilterMode) {
  taskDateFilterMode.value = mode
}

const taskSettingsLocked = computed(() =>
  ['starting', 'running', 'stopping', 'cancelling'].includes(taskStatus.value.status),
)

const taskStatusLabel = computed(() => {
  if (homeRuntimeState.value === 'detecting') {
    return '检测主页窗口中'
  }

  if (taskStatus.value.status === 'idle') {
    return homeSnapshot.value.statusLabel || '待准备'
  }

  const labels: Record<string, string> = {
    idle: '待机',
    starting: '启动中',
    running: '采集中',
    stopped: '已停止',
    success: '已完成',
    failed: '异常',
    cancelled: '已停止',
    error: '异常',
    'browser-preview': '浏览器预览',
  }

  return labels[taskStatus.value.status] ?? taskStatus.value.status
})

const taskStatusTone = computed<Tone>(() => {
  if (homeRuntimeState.value === 'detecting') {
    return 'blue'
  }

  if (taskStatus.value.status === 'running') {
    return 'green'
  }

  if (taskStatus.value.status === 'success') {
    return 'green'
  }

  if (homeSnapshot.value.status === 'ready') {
    return 'blue'
  }

  if (['not_found', 'failed', 'dependency_missing', 'content_unreadable'].includes(homeSnapshot.value.status)) {
    return 'red'
  }

  if (taskStatus.value.status === 'error' || taskStatus.value.status === 'failed') {
    return 'red'
  }

  return 'orange'
})

const HEALTH_CHECK_TARGETS: HealthCheckTarget[] = ['storage', 'ca', 'proxy-port', 'https']
const HEALTH_CHECK_META: Record<HealthCheckTarget, { label: string; icon: string }> = {
  https: { label: 'HTTPS 状态', icon: 'fa-solid fa-lock' },
  ca: { label: 'CA 证书', icon: 'fa-solid fa-shield-halved' },
  'proxy-port': { label: '代理端口', icon: 'fa-solid fa-network-wired' },
  storage: { label: '数据目录', icon: 'fa-solid fa-database' },
}

function buildTopbarCheckingState(message = '正在检测，请稍候...'): TopbarHealthState {
  return {
    value: '检测中',
    statusIcon: 'fa-solid fa-rotate',
    tone: 'warning',
    message,
    items: [],
    checkedAt: '',
    checking: true,
  }
}

const topbarHealthStates = ref<Record<HealthCheckTarget, TopbarHealthState>>({
  https: buildTopbarCheckingState('正在验证 HTTPS 代理链路...'),
  ca: buildTopbarCheckingState('正在比对项目证书与系统证书指纹...'),
  'proxy-port': buildTopbarCheckingState('正在检测代理端口占用状态...'),
  storage: buildTopbarCheckingState('正在检测配置目录读写权限...'),
})
const healthDialogVisible = ref(false)
const healthDialogTarget = ref<HealthCheckTarget>('https')
const healthCheckInProgress = ref<HealthCheckTarget | null>(null)
const startupHealthCheckRunning = ref(false)
const healthDialogMeta = computed(() => HEALTH_CHECK_META[healthDialogTarget.value])
const healthDialogState = computed(() => topbarHealthStates.value[healthDialogTarget.value])
const startupSelfCheckDialogVisible = ref(false)
const startupSelfCheckDialogState = ref<TopbarHealthState>(buildTopbarCheckingState('正在自检，请稍候...'))

function normalizeTopbarHealthValue(result: HealthCheckResult) {
  // 顶部空间有限，只显示短状态；完整原因仍保留在弹窗 message 和 items 中。
  if (result.ok) {
    return '正常'
  }

  return '异常'
}

function applyHealthCheckResult(result: HealthCheckResult) {
  topbarHealthStates.value[result.target] = {
    value: normalizeTopbarHealthValue(result),
    statusIcon: result.ok
      ? 'fa-solid fa-circle-check'
      : 'fa-solid fa-triangle-exclamation',
    tone: result.tone,
    message: result.message,
    items: result.items,
    checkedAt: result.checkedAt,
    checking: false,
  }
}

function applyHealthCheckFailure(target: HealthCheckTarget, message: string) {
  topbarHealthStates.value[target] = {
    value: '失败',
    statusIcon: 'fa-solid fa-triangle-exclamation',
    tone: 'danger',
    message,
    items: [],
    checkedAt: new Date().toISOString().slice(0, 19),
    checking: false,
  }
}

const topbarHealthItems = computed(() => [
  {
    key: 'https' as const,
    label: 'HTTPS 状态',
    value: topbarHealthStates.value.https.value,
    icon: 'fa-solid fa-lock',
    statusIcon: topbarHealthStates.value.https.statusIcon,
    tone: topbarHealthStates.value.https.tone,
    checking: topbarHealthStates.value.https.checking,
    disabled: startupHealthCheckRunning.value || healthCheckInProgress.value !== null,
  },
  {
    key: 'ca' as const,
    label: 'CA 证书',
    value: topbarHealthStates.value.ca.value,
    icon: 'fa-solid fa-shield-halved',
    statusIcon: topbarHealthStates.value.ca.statusIcon,
    tone: topbarHealthStates.value.ca.tone,
    checking: topbarHealthStates.value.ca.checking,
    disabled: startupHealthCheckRunning.value || healthCheckInProgress.value !== null,
  },
  {
    key: 'proxy-port' as const,
    label: '代理端口',
    value: topbarHealthStates.value['proxy-port'].value,
    icon: 'fa-solid fa-network-wired',
    statusIcon: topbarHealthStates.value['proxy-port'].statusIcon,
    tone: topbarHealthStates.value['proxy-port'].tone,
    checking: topbarHealthStates.value['proxy-port'].checking,
    disabled: startupHealthCheckRunning.value || healthCheckInProgress.value !== null,
  },
  {
    key: 'storage' as const,
    label: '数据目录',
    value: topbarHealthStates.value.storage.value,
    icon: 'fa-solid fa-database',
    statusIcon: topbarHealthStates.value.storage.statusIcon,
    tone: topbarHealthStates.value.storage.tone,
    checking: topbarHealthStates.value.storage.checking,
    disabled: startupHealthCheckRunning.value || healthCheckInProgress.value !== null,
  },
])

const trafficStatus = computed(() => taskStatus.value.traffic ?? defaultTrafficStatus)
const trafficUploadLabel = computed(() => (
  trafficStatus.value.uploadLabel || formatTrafficRate(trafficStatus.value.uploadBytesPerSecond)
))
const trafficDownloadLabel = computed(() => (
  trafficStatus.value.downloadLabel || formatTrafficRate(trafficStatus.value.downloadBytesPerSecond)
))
const trafficHistory = computed(() => trafficStatus.value.history ?? [])
const runtimeState = computed<TaskRuntimeState>(() => ({
  ...defaultRuntimeState,
  ...(taskStatus.value.runtimeState ?? {}),
}))

const taskProgressSummary = computed(() => resolveTaskProgressSummary({
  plannedCount: normalizedPageCount.value,
  logs: taskLogs.value,
}))
const taskProgressLabel = computed(() => (
  `${runtimeState.value.progressDone ?? taskProgressSummary.value.completedCount}/${runtimeState.value.progressTotalLabel || taskProgressSummary.value.totalLabel}`
))

const logTabs = [
  { level: 'ALL', label: 'ALL' },
  { level: 'INFO', label: 'INFO' },
  { level: 'SUCCESS', label: 'SUCCESS' },
  { level: 'WARN', label: 'WARN' },
  { level: 'ERROR', label: 'ERROR' },
] satisfies { level: LogFilterLevel; label: string }[]

const logLevelLabels = {
  INFO: 'INFO',
  SUCCESS: 'SUCCESS',
  WARN: 'WARN',
  ERROR: 'ERROR',
} satisfies Record<RuntimeLogLevel, string>

const logDisplayRows = computed<LogDisplayRow[]>(() => {
  const mergedLogs = [...taskLogs.value, ...frontendRuntimeLogs.value]
    .sort((left, right) => String(left.createdAt || '').localeCompare(String(right.createdAt || '')))
  const rows = mergedLogs.map((item, index) => {
    const level = normalizeLogLevel(item.level)

    return {
      id: `${item.createdAt || 'unknown'}-${item.source || 'runtime'}-${index}-${item.message}`,
      time: formatLogTime(item.createdAt),
      level,
      levelLabel: logLevelLabels[level],
      levelClass: level.toLowerCase(),
      message: item.message,
      messageSegments: formatLogMessageSegments(item.message),
      source: item.source || 'runtime',
    }
  })

  return rows.filter((item) => activeLogLevel.value === 'ALL' || item.level === activeLogLevel.value)
})

const statusItems = computed(() => [
  {
    label: '当前状态',
    value: taskStatusLabel.value,
    icon: 'fa-solid fa-circle-play',
    tag: true,
    tone: taskStatusTone.value,
  },
  { label: '当前动作', value: runtimeState.value.currentAction || '待获取', icon: 'fa-solid fa-bolt' },
  { label: '公众号名称', value: runtimeState.value.accountName || '等待识别', icon: 'fa-brands fa-weixin' },
  { label: '任务信息', value: runtimeState.value.taskInfo || '待获取', icon: 'fa-regular fa-file-lines' },
  { label: '代理状态', value: runtimeState.value.proxyStatusLabel || '空闲', icon: 'fa-solid fa-network-wired' },
  { label: '采集进度', value: '', icon: 'fa-solid fa-gauge-high', progress: true },
  { label: '平均时长', value: runtimeState.value.averageArticleDurationLabel || '待统计', icon: 'fa-regular fa-clock' },
  {
    label: '活跃子进程',
    value: `${runtimeState.value.activeWorkerCount ?? 0}/${runtimeState.value.totalWorkerCount ?? 0}`,
    icon: 'fa-solid fa-list-check',
  },
  {
    label: '异常记录',
    value: String(runtimeState.value.errorCount ?? taskProgressSummary.value.failedCount),
    icon: 'fa-solid fa-triangle-exclamation',
    tone: 'red' as Tone,
  },
])

const stats = computed(() => buildArchiveSummaryStats(archiveSummary.value, formatDuration(uptimeSeconds.value)))

const mandatoryDownloadOption = { key: 'articleDetail', label: '文章详情', locked: true } as const

const downloadOptions = [
  { key: 'offlineArchive', label: '离线归档', locked: false },
  { key: 'commentInfo', label: '评论信息', locked: false },
  { key: 'skipCollectedRecords', label: '跳过已采集记录', locked: false },
] as const

const usageTips = [
  '点击开始运行前打开目标 PC 端',
  '手动打开目标公众号主页窗口',
  '开始运行后将自动读取主页信息',
  '出现跳转操作时无需手动干预',
]

const complianceTips = [
  '本工具仅用于学习研究与合规用途',
  '整理公开文章材料、字段内容记录',
  '不存储、分享或发布任何侵权内容',
  '请遵守相关法律、政策和平台条款',
]

const envItems = computed(() => [
  { name: 'Version', value: environmentStatus.value.appVersion, icon: 'fa-solid fa-cube' },
  { name: 'Python', value: environmentStatus.value.pythonVersion, icon: 'fa-brands fa-python' },
  { name: 'System', value: environmentStatus.value.systemLabel, icon: 'fa-brands fa-windows' },
  { name: 'PyWebView', value: environmentStatus.value.pywebviewVersion, icon: 'fa-regular fa-window-maximize' },
  { name: 'MITMproxy', value: environmentStatus.value.mitmproxyVersion, icon: 'fa-solid fa-shield-halved' },
  { name: 'Playwright', value: environmentStatus.value.playwrightVersion, icon: 'fa-solid fa-window-restore' },
])

const progressPercent = computed(() => {
  const runtimeProgress = Number(runtimeState.value.progressPercent)
  if (Number.isFinite(runtimeProgress)) {
    return Math.min(100, Math.max(0, Math.round(runtimeProgress)))
  }

  return taskProgressSummary.value.progressPercent
})
const pageStepperWidth = computed(() => {
  const digitCount = String(pageCount.value ?? '').length
  const width = 148 + Math.max(0, digitCount - 1) * 14

  return `${Math.min(width, 244)}px`
})

function setPageCount(delta: number) {
  if (taskSettingsLocked.value) {
    return
  }

  pageCount.value = Math.max(0, pageCount.value + delta)
}

function stopPageCountHold() {
  window.clearTimeout(pageHoldDelayTimer)
  window.clearInterval(pageHoldIntervalTimer)
  pageHoldDelayTimer = undefined
  pageHoldIntervalTimer = undefined
}

function cancelPageCountHold() {
  stopPageCountHold()
  isHoldingPageStep.value = false
}

watch(taskSettingsLocked, (locked) => {
  if (locked) {
    cancelPageCountHold()
  }
})

function parseConfigSwitchValue(value: unknown, fallback: boolean) {
  if (typeof value === 'boolean') {
    return value
  }

  if (typeof value !== 'string') {
    return fallback
  }

  const normalized = value.trim().toLowerCase()
  if (['开启', '开', 'true', '1', 'yes', 'on'].includes(normalized)) {
    return true
  }
  if (['关闭', '关', 'false', '0', 'no', 'off'].includes(normalized)) {
    return false
  }

  return fallback
}

function applyMainTaskSelectionDefaults(values?: Record<string, string>) {
  // YAML 只负责主服务页初始勾选状态；用户手动切换后不能再被状态轮询覆盖。
  if (mainTaskSelectionDefaultsApplied.value || taskSettingsLocked.value || !values) {
    return
  }

  downloadSelections.value.commentInfo = parseConfigSwitchValue(
    values['data_acquisition.comment_collection.enabled_by_default'],
    downloadSelections.value.commentInfo,
  )
  downloadSelections.value.offlineArchive = parseConfigSwitchValue(
    values['data_acquisition.offline_cache.enabled_by_default'],
    downloadSelections.value.offlineArchive,
  )
  mainTaskSelectionDefaultsApplied.value = true
}

// 输入框两侧按钮支持长按连续增减，方便批量调整任务数量。
function startPageCountHold(delta: number) {
  if (taskSettingsLocked.value) {
    return
  }

  stopPageCountHold()
  isHoldingPageStep.value = false
  pageHoldDelayTimer = window.setTimeout(() => {
    isHoldingPageStep.value = true
    setPageCount(delta)
    pageHoldIntervalTimer = window.setInterval(() => setPageCount(delta), 120)
  }, 360)
}

function handlePageStep(delta: number) {
  if (isHoldingPageStep.value) {
    isHoldingPageStep.value = false
    return
  }

  setPageCount(delta)
}

function toggleDownloadOption(key: keyof typeof downloadSelections.value) {
  if (taskSettingsLocked.value) {
    return
  }

  mainTaskSelectionDefaultsApplied.value = true
  if (key === 'articleDetail') {
    downloadSelections.value.articleDetail = true
    return
  }
  downloadSelections.value[key] = !downloadSelections.value[key]
}

function buildTaskRunOptions(): TaskRunOptions {
  return {
    recordLimit: normalizedPageCount.value,
    selections: {
      articleDetail: true,
      offlineArchive: downloadSelections.value.offlineArchive,
      commentInfo: downloadSelections.value.commentInfo,
      skipCollectedRecords: downloadSelections.value.skipCollectedRecords,
    },
  }
}

function markHomeDetectionStarting() {
  homeRuntimeState.value = 'detecting'
}

function markTaskStarting() {
  taskStatus.value = {
    ...taskStatus.value,
    ok: true,
    status: 'starting',
  }
  homeRuntimeState.value = 'detecting'
}

function getTooltipPoint(event: MouseEvent | FocusEvent) {
  if ('clientX' in event && event.clientX > 0) {
    return { x: event.clientX, y: event.clientY }
  }

  const target = event.currentTarget as HTMLElement | null
  const rect = target?.getBoundingClientRect()
  if (!rect) {
    return { x: 0, y: 0 }
  }

  return { x: rect.left + rect.width / 2, y: rect.bottom }
}

function updateDescriptionTooltipPosition(event: MouseEvent | FocusEvent) {
  const point = getTooltipPoint(event)
  const maxLeft = Math.max(12, window.innerWidth - 372)
  const maxTop = Math.max(12, window.innerHeight - 220)

  descriptionTooltip.value.x = Math.min(Math.max(12, point.x + 14), maxLeft)
  descriptionTooltip.value.y = Math.min(Math.max(12, point.y + 14), maxTop)
}

function isStatusValueOverflowing(event: MouseEvent | FocusEvent) {
  const target = event.currentTarget as HTMLElement | null
  if (!target) {
    return false
  }

  return target.scrollWidth > target.clientWidth
}

function showDescriptionTooltip(event: MouseEvent | FocusEvent, text: string) {
  const value = String(text || '').trim()
  if (!value) {
    return
  }

  descriptionTooltip.value.visible = true
  descriptionTooltip.value.text = value
  updateDescriptionTooltipPosition(event)
}

function showStatusValueTooltip(event: MouseEvent | FocusEvent, text: string) {
  const value = String(text || '').trim()
  if (!value || !isStatusValueOverflowing(event)) {
    hideDescriptionTooltip()
    return
  }

  descriptionTooltip.value.visible = true
  descriptionTooltip.value.text = value
  updateDescriptionTooltipPosition(event)
}

function moveDescriptionTooltip(event: MouseEvent) {
  if (!descriptionTooltip.value.visible) {
    return
  }

  updateDescriptionTooltipPosition(event)
}

function hideDescriptionTooltip() {
  descriptionTooltip.value.visible = false
}

function selectPage(page: PageKey | null) {
  if (page) {
    activePage.value = page
  }
}

function formatDuration(totalSeconds: number) {
  const safeSeconds = Math.max(0, Math.floor(totalSeconds))
  const hours = Math.floor(safeSeconds / 3600)
  const minutes = Math.floor((safeSeconds % 3600) / 60)
  const seconds = safeSeconds % 60

  return [hours, minutes, seconds].map((item) => String(item).padStart(2, '0')).join(':')
}

function formatTrafficRate(bytesPerSecond: number) {
  const safeValue = Math.max(0, Number(bytesPerSecond) || 0)
  if (safeValue <= 0) {
    return '0 KB/s'
  }

  const kib = safeValue / 1024
  if (kib < 1024) {
    return `${Number(kib.toFixed(1))} KB/s`
  }

  return `${Number((kib / 1024).toFixed(1))} MB/s`
}

function normalizeLogLevel(level: string): RuntimeLogLevel {
  const normalized = String(level || 'INFO').toUpperCase()
  if (normalized === 'SUCCESS' || normalized === 'WARN' || normalized === 'ERROR') {
    return normalized
  }

  return 'INFO'
}

function formatLogTime(createdAt: string) {
  const value = String(createdAt || '').trim()
  if (!value) {
    return '--:--:--'
  }

  const timeText = value.includes('T') ? value.split('T')[1] : value.split(' ')[1]
  return (timeText || value).slice(0, 8) || '--:--:--'
}

function formatErrorMessage(error: unknown) {
  if (error instanceof Error) {
    return error.message
  }

  return String(error || '未知异常')
}

async function refreshStartupHealthChecks() {
  if (startupHealthCheckRequested) {
    return
  }
  startupHealthCheckRequested = true
  startupHealthCheckRunning.value = true
  for (const target of HEALTH_CHECK_TARGETS) {
    topbarHealthStates.value[target] = buildTopbarCheckingState(
      `正在执行${HEALTH_CHECK_META[target].label}启动检测...`,
    )
  }

  try {
    const result = await runStartupHealthChecks()
    for (const target of HEALTH_CHECK_TARGETS) {
      const healthResult = result.results[target]
      if (healthResult) {
        applyHealthCheckResult(healthResult)
      } else {
        applyHealthCheckFailure(target, `${HEALTH_CHECK_META[target].label}未返回检测结果。`)
      }
    }
  } catch (error) {
    const message = `启动健康检测失败：${formatErrorMessage(error)}`
    for (const target of HEALTH_CHECK_TARGETS) {
      applyHealthCheckFailure(target, message)
    }
    appendFrontendRuntimeError(message)
  } finally {
    startupHealthCheckRunning.value = false
  }
}

function buildStartupSelfCheckItems(result: StartupSelfCheckResult): HealthCheckResult['items'] {
  return result.items.map((item) => ({
    key: item.key,
    label: item.label,
    value: item.message,
    message: item.action || '',
    ok: item.ok,
  }))
}

function applyStartupSelfCheckResult(result: StartupSelfCheckResult) {
  const hasWarning = result.warningCount > 0
  startupSelfCheckDialogState.value = {
    value: result.ok ? (hasWarning ? '有警告' : '通过') : '异常',
    statusIcon: result.ok
      ? 'fa-solid fa-circle-check'
      : 'fa-solid fa-triangle-exclamation',
    tone: result.ok ? (hasWarning ? 'warning' : 'success') : 'danger',
    message: result.ok
      ? '自检完成：' + result.fatalCount + ' 个致命问题，' + result.warningCount + ' 个警告。'
      : '自检发现 ' + result.fatalCount + ' 个致命问题，' + result.warningCount + ' 个警告。',
    items: buildStartupSelfCheckItems(result),
    checkedAt: result.checkedAt,
    checking: false,
  }
}

async function refreshStartupSelfCheck() {
  if (startupSelfCheckRequested) {
    return
  }
  startupSelfCheckRequested = true

  try {
    const status = await getStartupSelfCheckStatus()
    if (!status.needsSelfCheck) {
      return
    }

    startupSelfCheckDialogState.value = buildTopbarCheckingState('正在自检：检查程序运行环境、MITM、Playwright、SQLite 和存储配置...')
    startupSelfCheckDialogVisible.value = true
    const result = await runStartupSelfCheck()
    applyStartupSelfCheckResult(result)
    if (!result.ok) {
      appendFrontendRuntimeError('启动自检发现 ' + result.fatalCount + ' 个致命问题。')
    }
  } catch (error) {
    const message = '启动自检失败：' + formatErrorMessage(error)
    startupSelfCheckDialogVisible.value = true
    startupSelfCheckDialogState.value = {
      value: '失败',
      statusIcon: 'fa-solid fa-triangle-exclamation',
      tone: 'danger',
      message,
      items: [],
      checkedAt: new Date().toISOString().slice(0, 19),
      checking: false,
    }
    appendFrontendRuntimeError(message)
  }
}

async function handleTopbarHealthCheck(target: HealthCheckTarget) {
  if (startupHealthCheckRunning.value || healthCheckInProgress.value !== null) return
  healthDialogTarget.value = target
  healthDialogVisible.value = true
  const checkingState = buildTopbarCheckingState(`正在重新检测${HEALTH_CHECK_META[target].label}...`)
  topbarHealthStates.value[target] = checkingState
  healthCheckInProgress.value = target

  try {
    const result = await checkHealthTarget(target)
    applyHealthCheckResult(result)
  } catch (error) {
    const message = `${HEALTH_CHECK_META[target].label}检测失败：${formatErrorMessage(error)}`
    applyHealthCheckFailure(target, message)
    appendFrontendRuntimeError(message)
  } finally {
    healthCheckInProgress.value = null
  }
}

function appendFrontendRuntimeError(message: string) {
  const latest = frontendRuntimeLogs.value[frontendRuntimeLogs.value.length - 1]
  if (latest?.message === message) {
    return
  }

  frontendRuntimeLogs.value = [
    ...frontendRuntimeLogs.value,
    {
      level: 'ERROR',
      message,
      source: 'frontend',
      createdAt: new Date().toISOString().slice(0, 19),
    },
  ].slice(-LOG_POLL_LIMIT)
}

async function scrollLogTableToLatest() {
  await nextTick()
  if (!logDisplayRows.value.length || !shouldStickLogToBottom.value) {
    return
  }

  logScrollerRef.value?.scrollToBottom()
}

function stopLogAutoFollowTimer() {
  window.clearTimeout(logAutoFollowTimer)
  logAutoFollowTimer = undefined
}

function scheduleLogAutoFollowResume() {
  stopLogAutoFollowTimer()
  if (shouldStickLogToBottom.value) {
    return
  }

  const lastInteractionAt = lastLogScrollUserInteractionAt.value || Date.now()
  const elapsed = Date.now() - lastInteractionAt
  const delay = Math.max(0, LOG_AUTO_FOLLOW_IDLE_MS - elapsed)
  logAutoFollowTimer = window.setTimeout(async () => {
    if (!canResumeLogAutoFollow(lastLogScrollUserInteractionAt.value, Date.now())) {
      scheduleLogAutoFollowResume()
      return
    }

    shouldStickLogToBottom.value = true
    await scrollLogTableToLatest()
  }, delay)
}

function markLogScrollUserInteraction() {
  lastLogScrollUserInteractionAt.value = Date.now()
  scheduleLogAutoFollowResume()
}

async function selectLogLevel(level: LogFilterLevel) {
  activeLogLevel.value = level
  shouldStickLogToBottom.value = true
  stopLogAutoFollowTimer()
  await scrollLogTableToLatest()
}

function handleLogTableScroll(event: Event) {
  const metrics = readLogScrollMetricsFromEvent(event)
  if (!metrics) {
    return
  }

  const nearBottom = isLogScrollNearBottom(metrics)
  shouldStickLogToBottom.value = nearBottom
  if (nearBottom) {
    stopLogAutoFollowTimer()
    return
  }

  scheduleLogAutoFollowResume()
}

function stopPywebviewStatusRetry() {
  window.clearTimeout(pywebviewStatusRetryTimer)
  pywebviewStatusRetryTimer = undefined
}

function applyPywebviewEnvironmentStatus(resolved: ResolvedPywebviewEnvironmentStatus) {
  pywebviewStatusLabel.value = resolved.pywebviewStatusLabel
  environmentStatus.value = resolved.environmentStatus
}

function schedulePywebviewStatusRetry() {
  stopPywebviewStatusRetry()

  if (pywebviewStatusRetryCount >= MAX_PYWEBVIEW_STATUS_RETRIES) {
    applyPywebviewEnvironmentStatus(getBrowserPreviewEnvironmentStatus())
    return
  }

  pywebviewStatusRetryCount += 1
  pywebviewStatusRetryTimer = window.setTimeout(() => {
    refreshPythonStatus()
  }, PYWEBVIEW_STATUS_RETRY_DELAY_MS)
}

async function refreshPythonStatus() {
  try {
    const status = await getPythonStatus()
    const resolved = resolvePywebviewEnvironmentStatus(status)
    applyPywebviewEnvironmentStatus(resolved)

    if (resolved.shouldRetry) {
      schedulePywebviewStatusRetry()
      return
    }

    stopPywebviewStatusRetry()
  } catch {
    stopPywebviewStatusRetry()
    applyPywebviewEnvironmentStatus(getEnvironmentErrorStatus())
  }
}

function handlePywebviewReady() {
  stopPywebviewStatusRetry()
  pywebviewStatusRetryCount = 0
  refreshPythonStatus()
}

function stopTaskPolling() {
  window.clearInterval(taskPollingTimer)
  taskPollingTimer = undefined
}

async function refreshTaskRuntime() {
  try {
    const [status, logs] = await Promise.all([getTaskStatus(), getTaskLogs(LOG_POLL_LIMIT)])
    taskStatus.value = status
    applyMainTaskSelectionDefaults(status.config?.values)
    uptimeSeconds.value = status.uptimeSeconds ?? uptimeSeconds.value
    taskLogs.value = Array.isArray(logs.items) ? logs.items : []
    homeRuntimeState.value = status.status === 'running' ? 'running' : 'idle'
    syncTaskPolling(status)
  } catch (error) {
    appendFrontendRuntimeError(`读取运行状态失败：${formatErrorMessage(error)}`)
  }
}

async function refreshArchiveSummary() {
  try {
    archiveSummary.value = await listArchiveSummary()
  } catch (error) {
    archiveSummary.value = null
    appendFrontendRuntimeError(`读取数据统计失败：${formatErrorMessage(error)}`)
  }
}

function handleTaskStatusChanged(status: TaskStatus) {
  taskStatus.value = status
  applyMainTaskSelectionDefaults(status.config?.values)
  uptimeSeconds.value = status.uptimeSeconds ?? uptimeSeconds.value
  syncTaskPolling(status)
}

function startTaskPolling() {
  if (taskPollingTimer !== undefined) {
    return
  }

  taskPollingTimer = window.setInterval(() => {
    refreshTaskRuntime()
  }, 1500)
}

function shouldPollTaskRuntime(status: TaskStatus) {
  return status.status === 'starting' || status.status === 'running'
}

// 诊断接口可能返回 managed-by-capture，这类结果不代表采集任务已结束。
function isTaskLifecycleStatus(status: TaskStatus) {
  return ['idle', 'starting', 'running', 'stopped', 'error'].includes(status.status)
}

function syncTaskPolling(status: TaskStatus) {
  if (shouldPollTaskRuntime(status)) {
    startTaskPolling()
    return
  }

  if (!isTaskLifecycleStatus(status)) {
    return
  }

  stopTaskPolling()
}

function stopUptimeTimer() {
  window.clearInterval(uptimeTimer)
  uptimeTimer = undefined
}

function startUptimeTimer() {
  stopUptimeTimer()
  uptimeTimer = window.setInterval(() => {
    uptimeSeconds.value += 1
  }, 1000)
}

async function handleStartTask() {
  const actionVersion = ++taskActionVersion
  markHomeDetectionStarting()
  markTaskStarting()
  shouldStickLogToBottom.value = true
  stopLogAutoFollowTimer()
  try {
    const startedStatus = await startTask(buildTaskRunOptions())
    if (actionVersion !== taskActionVersion) {
      return
    }
    taskStatus.value = startedStatus
    homeRuntimeState.value = taskStatus.value.status === 'running' ? 'running' : 'idle'
    syncTaskPolling(startedStatus)
    await refreshTaskRuntime()
    if (actionVersion !== taskActionVersion) {
      return
    }
    await refreshArchiveSummary()
    homeRuntimeState.value = taskStatus.value.status === 'running' ? 'running' : 'idle'
    startTaskPolling()
  } catch (error) {
    if (actionVersion !== taskActionVersion) {
      return
    }
    if (taskStatus.value.status === 'starting') {
      taskStatus.value = {
        ...taskStatus.value,
        ok: false,
        status: 'error',
      }
    }
    homeRuntimeState.value = 'idle'
    appendFrontendRuntimeError(`启动采集任务失败：${formatErrorMessage(error)}`)
  }
}

async function handleStopTask() {
  taskActionVersion += 1
  homeRuntimeState.value = 'idle'
  try {
    taskStatus.value = await stopTask()
    await refreshTaskRuntime()
    await refreshArchiveSummary()
    stopTaskPolling()
  } catch (error) {
    appendFrontendRuntimeError(`停止采集任务失败：${formatErrorMessage(error)}`)
  }
}

async function handleOpenLogFolder() {
  try {
    const result = await openRuntimePath('logDir')
    if (!result.ok) {
      appendFrontendRuntimeError(result.message || '打开日志目录失败。')
    }
  } catch (error) {
    appendFrontendRuntimeError(`打开日志目录失败：${formatErrorMessage(error)}`)
  }
}

onMounted(async () => {
  markHomeDetectionStarting()
  window.addEventListener('pywebviewready', handlePywebviewReady)
  refreshPythonStatus()
  refreshArchiveSummary()
  startUptimeTimer()
  await refreshTaskRuntime()
  await refreshStartupSelfCheck()
  await refreshStartupHealthChecks()
})
watch(logDisplayRows, async () => {
  await scrollLogTableToLatest()
}, { flush: 'post' })
onBeforeUnmount(() => {
  stopPageCountHold()
  stopPywebviewStatusRetry()
  stopLogAutoFollowTimer()
  stopTaskPolling()
  stopUptimeTimer()
  window.removeEventListener('pywebviewready', handlePywebviewReady)
})
</script>

<template>
  <AConfigProvider :locale="zhCN" :theme="antThemeConfig">
    <main :class="['collector-app', { dark: isDark }]">
    <section class="workspace">
      <AppTopbar
        :is-dark="isDark"
        :github-url="githubUrl"
        :health-items="topbarHealthItems"
        @toggle-theme="isDark = !isDark"
        @health-check="handleTopbarHealthCheck"
      />

      <div class="dashboard">
        <aside class="sidebar panel">
          <nav
            v-for="group in navGroups"
            :key="group.title"
            class="nav-group"
            :aria-label="group.title"
          >
            <p class="nav-title">{{ group.title }} <span aria-hidden="true">⌁</span></p>
            <template
              v-for="item in group.items"
              :key="item.label"
            >
              <a
                v-if="item.href"
                class="nav-item"
                :href="item.href"
                target="_blank"
                rel="noopener noreferrer"
              >
                <AppIcon :icon="['nav-icon', item.icon]" />
                {{ item.label }}
              </a>
              <button
                v-else
                :class="['nav-item', { active: item.page === activePage }]"
                type="button"
                :disabled="!item.page"
                :aria-current="item.page === activePage ? 'page' : undefined"
                @click="selectPage(item.page)"
              >
                <AppIcon :icon="['nav-icon', item.icon]" />
                {{ item.label }}
              </button>
            </template>
          </nav>

          <img class="sidebar-book" src="/assets/watercolor-book-stack.png" alt="" />
        </aside>

        <template v-if="activePage === 'home'">
        <section class="task-column" aria-label="采集任务设置">
          <article class="task-card task-card-volume panel">
            <span class="step-badge">01</span>
            <img class="task-art task-art-list" src="/assets/watercolor-task-list.png" alt="" />
            <div class="task-volume-body">
              <h2>指定记录总量</h2>
              <div class="task-volume-row task-date-filter-row">
                <span class="task-control-label">日期筛选</span>
                <ADropdown
                  :trigger="['click']"
                  :disabled="taskSettingsLocked"
                  placement="bottomLeft"
                  overlay-class-name="task-date-filter-dropdown"
                >
                  <AButton
                    class="task-date-filter-trigger"
                    :disabled="taskSettingsLocked"
                    aria-label="日期筛选方式"
                  >
                    <span>{{ taskDateFilterLabel }}</span>
                    <AppIcon class="task-date-filter-chevron" icon="fa-solid fa-chevron-down" />
                  </AButton>
                  <template #overlay>
                    <AMenu :selected-keys="[taskDateFilterMode]">
                      <AMenuItem
                        v-for="option in taskDateFilterOptions"
                        :key="option.value"
                        @click="selectTaskDateFilterMode(option.value)"
                      >
                        {{ option.label }}
                      </AMenuItem>
                    </AMenu>
                  </template>
                </ADropdown>
              </div>

              <div class="task-volume-row task-count-row">
                <label class="task-control-label" for="page-count">任务数量</label>
                <div class="task-count-control">
                  <div class="number-stepper" :style="{ width: pageStepperWidth }">
                    <button
                      type="button"
                      aria-label="减少任务数量，长按连续减少"
                      :disabled="taskSettingsLocked"
                      @click="handlePageStep(-1)"
                      @pointerdown="startPageCountHold(-1)"
                      @pointerup="stopPageCountHold"
                      @pointerleave="cancelPageCountHold"
                      @pointercancel="cancelPageCountHold"
                    >
                      −
                    </button>
                    <input
                      id="page-count"
                      v-model.number="pageCount"
                      type="number"
                      min="0"
                      :disabled="taskSettingsLocked"
                    />
                    <button
                      type="button"
                      aria-label="增加任务数量，长按连续增加"
                      :disabled="taskSettingsLocked"
                      @click="handlePageStep(1)"
                      @pointerdown="startPageCountHold(1)"
                      @pointerup="stopPageCountHold"
                      @pointerleave="cancelPageCountHold"
                      @pointercancel="cancelPageCountHold"
                    >
                      +
                    </button>
                  </div>
                  <button
                    class="task-count-hint"
                    type="button"
                    aria-label="查看任务数量说明"
                    aria-describedby="description-tooltip"
                    @mouseenter="showDescriptionTooltip($event, '设为0时遍历日期范围内全部内容')"
                    @mousemove="moveDescriptionTooltip"
                    @mouseleave="hideDescriptionTooltip"
                    @focus="showDescriptionTooltip($event, '设为0时遍历日期范围内全部内容')"
                    @blur="hideDescriptionTooltip"
                  >
                    <AppIcon icon="fa-regular fa-circle-question" />
                  </button>
                </div>
              </div>

              <label class="task-volume-row task-date-row">
                <span class="task-control-label task-date-label download-option selected locked">
                  <ASpin class="task-date-label-spin" size="small" :spinning="true" />
                  {{ taskDateFieldLabel }}
                </span>
                <span class="task-date-control">
                  <ARangePicker
                    v-if="taskDateFilterMode === 'range'"
                    v-model:value="taskDateRangeValue"
                    class="task-date-picker task-date-range-picker"
                    :allow-clear="true"
                    :placeholder="['选择起始日期', '选择截止日期']"
                    format="YYYY-MM-DD"
                    value-format="YYYY-MM-DD"
                    popup-class-name="task-date-picker-panel"
                    :disabled="taskSettingsLocked"
                    aria-label="任务日期范围"
                  />
                  <ADatePicker
                    v-else-if="taskDateFilterMode === 'before'"
                    v-model:value="taskEndDate"
                    class="task-date-picker"
                    :allow-clear="true"
                    placeholder="选择截止日期"
                    format="YYYY-MM-DD  dddd"
                    value-format="YYYY-MM-DD"
                    popup-class-name="task-date-picker-panel"
                    :disabled="taskSettingsLocked"
                    aria-label="任务截止日期"
                  />
                  <ADatePicker
                    v-else-if="taskDateFilterMode === 'after'"
                    v-model:value="taskStartDate"
                    class="task-date-picker"
                    :allow-clear="true"
                    placeholder="选择起始日期"
                    format="YYYY-MM-DD  dddd"
                    value-format="YYYY-MM-DD"
                    popup-class-name="task-date-picker-panel"
                    :disabled="taskSettingsLocked"
                    aria-label="任务起始日期"
                  />
                  <ADatePicker
                    v-else-if="taskDateFilterMode === 'all'"
                    class="task-date-picker"
                    :value="null"
                    placeholder="不限日期，无需选择"
                    :disabled="true"
                    aria-label="不限日期"
                  />
                </span>
              </label>
            </div>
          </article>

          <article class="task-card task-card-content panel">
            <span class="step-badge">02</span>
            <div class="task-art-column">
              <img class="task-art task-art-heart" src="/assets/watercolor-task-heart.png" alt="" />
              <button
                :class="[
                  'download-option',
                  'article-detail-option',
                  {
                    selected: downloadSelections[mandatoryDownloadOption.key],
                    locked: mandatoryDownloadOption.locked || taskSettingsLocked,
                  },
                ]"
                type="button"
                role="checkbox"
                :aria-checked="downloadSelections[mandatoryDownloadOption.key]"
                :aria-disabled="mandatoryDownloadOption.locked || taskSettingsLocked"
                :disabled="mandatoryDownloadOption.locked || taskSettingsLocked"
                title="文章详情为必选项，不能取消"
                @click="toggleDownloadOption(mandatoryDownloadOption.key)"
              >
                <span class="option-box" aria-hidden="true">
                  <AppIcon icon="fa-solid fa-check" />
                </span>
                <span>{{ mandatoryDownloadOption.label }}</span>
              </button>
            </div>
            <div class="task-body task-body-content">
              <h2>获取指定内容</h2>
              <div class="download-options" aria-label="选择获取内容">
                <button
                  v-for="option in downloadOptions"
                  :key="option.key"
                  :class="[
                    'download-option',
                    {
                      selected: downloadSelections[option.key],
                      locked: option.locked || taskSettingsLocked,
                    },
                  ]"
                  type="button"
                  role="checkbox"
                  :aria-checked="downloadSelections[option.key]"
                  :aria-disabled="option.locked || taskSettingsLocked"
                  :disabled="option.locked || taskSettingsLocked"
                  :title="taskSettingsLocked ? '任务运行期间不能修改' : ''"
                  @click="toggleDownloadOption(option.key)"
                >
                  <span class="option-box" aria-hidden="true">
                    <AppIcon icon="fa-solid fa-check" />
                  </span>
                  <span>{{ option.label }}</span>
                </button>
              </div>
            </div>
          </article>

          <div class="control-panel panel" aria-label="任务控制">
            <button
              class="run-button"
              type="button"
              :disabled="taskStatus.status === 'running' || taskStatus.status === 'starting'"
              @click="handleStartTask"
            >
              <AppIcon icon="fa-solid fa-play" />
              <span class="button-label">开始运行</span>
            </button>
            <button
              class="stop-button"
              type="button"
              :disabled="taskStatus.status !== 'running' && taskStatus.status !== 'starting' && taskStatus.status !== 'error'"
              @click="handleStopTask"
            >
              <AppIcon icon="fa-solid fa-stop" />
              <span class="button-label">停止</span>
            </button>
          </div>
        </section>

        <section class="status-column">
          <article class="status-card panel sprig-corner status-corner">
            <!-- 右上角插画使用裁剪后的独立图片，直接贴边显示，不再做遮挡式装饰。 -->
            <img class="corner-image status-corner-image" src="/assets/watercolor-flower-corner.png" alt="" />
            <div class="section-title">
              <svg
                class="title-icon status-title-logo"
                viewBox="0 0 1024 1024"
                aria-hidden="true"
                focusable="false"
              >
                <path
                  fill="currentColor"
                  d="M41.984 486.4l56.32 0q22.528 0 36.352-4.096t27.136-15.36l16.384-16.384q10.24-10.24 21.504-23.552t23.04-27.136 22.016-26.112q20.48-25.6 36.864-19.968t24.576 24.064l45.056 123.904q34.816-97.28 61.44-176.128 11.264-33.792 22.528-66.048t20.48-59.392 15.36-45.056 7.168-23.04q5.12-17.408 15.36-28.16t22.528-10.752q13.312 0 27.648 7.68t18.432 31.232q1.024 6.144 4.096 32.768t8.192 66.56 10.752 88.576 11.776 98.816q13.312 117.76 30.72 263.168 22.528-73.728 40.96-134.144 7.168-25.6 14.848-50.688t14.336-46.08 10.752-35.328 6.144-18.432q5.12-16.384 12.288-24.576t19.456-11.264q23.552-6.144 35.328 6.656t11.776 26.112q0 11.264-2.048 19.456-1.024 4.096-1.024 7.168l36.864 100.352q1.024-1.024 3.072-4.096 3.072-5.12 10.24-21.504 8.192-17.408 27.136-23.04t36.352-4.608q11.264 1.024 22.528 1.024l22.528 0 24.576 0 0 77.824q-6.144 1.024-12.288 1.024l-26.624 0q-14.336-1.024-26.624 7.68t-17.408 16.896q-4.096 8.192-14.336 31.744t-18.432 48.128q-4.096 12.288-13.312 16.384t-18.944 3.584-18.432-5.632-11.776-12.288-10.24-25.088-14.336-36.352q-9.216-21.504-18.432-46.08-26.624 84.992-48.128 156.672-9.216 30.72-18.432 60.416t-16.896 54.784-12.8 42.496-6.144 23.552q-5.12 24.576-19.456 38.912t-34.816 13.312q-21.504-2.048-30.72-18.432t-11.264-37.888q0-5.12-2.56-31.744t-6.656-67.584-8.704-91.136-9.728-102.4q-11.264-121.856-26.624-272.384-28.672 83.968-51.2 150.528-9.216 28.672-18.944 56.32t-17.408 50.176-12.8 37.888l-6.144 18.432q-5.12 13.312-13.824 24.576t-27.136 10.24q-18.432 0-27.648-12.8t-14.336-29.184q-3.072-8.192-11.264-31.744t-17.408-48.128q-11.264-28.672-23.552-63.488-7.168 9.216-15.36 18.432-7.168 8.192-15.36 17.92t-16.384 18.944q-16.384 19.456-30.72 26.624t-33.792 5.12q-10.24-1.024-27.136-0.512t-34.304 0.512q-19.456 1.024-43.008 1.024l0-79.872z"
                />
              </svg>
              <h2>程序运行状态</h2>
            </div>

            <div class="status-list">
              <div
                v-for="item in statusItems"
                :key="item.label"
                :class="['status-row', { 'with-progress': item.progress }]"
              >
                <AppIcon :icon="['row-icon', item.icon]" />
                <span class="status-label">{{ item.label }}：</span>
                <span v-if="item.tag" :class="['status-pill', item.tone]">{{ item.value }}</span>
                <template v-else-if="item.progress">
                  <div class="progress-line" aria-label="采集进度">
                    <span :style="{ width: progressPercent + '%' }"></span>
                  </div>
                  <em>{{ taskProgressLabel }}</em>
                </template>
                <strong
                  v-else
                  :class="['status-value', 'status-value-ellipsis', 'status-description-value', item.tone]"
                  tabindex="0"
                  aria-describedby="description-tooltip"
                  @mouseenter="showStatusValueTooltip($event, item.value)"
                  @mousemove="moveDescriptionTooltip"
                  @mouseleave="hideDescriptionTooltip"
                  @focus="showStatusValueTooltip($event, item.value)"
                  @blur="hideDescriptionTooltip"
                >
                  {{ item.value }}
                </strong>
              </div>
            </div>

            <div class="network-panel">
              <div class="speed">
                <p>
                  <AppIcon icon="speed-icon fa-solid fa-chart-line" />
                  当前速率
                </p>
                <div class="speed-values">
                  <strong class="speed-upload">↑ {{ trafficUploadLabel }}</strong>
                  <strong class="speed-download">↓ {{ trafficDownloadLabel }}</strong>
                </div>
              </div>
              <TrafficSparkline class="mini-chart" :points="trafficHistory" />
            </div>
          </article>
        </section>

        <aside class="right-column" aria-label="辅助信息">
          <section class="stats-card panel sprig-corner">
            <!-- 右上角插画使用裁剪后的独立图片，直接贴边显示。 -->
            <img class="corner-image stats-corner-image" src="/assets/watercolor-leaf-branch-a.png" alt="" />
            <div class="section-title">
              <span class="title-icon stats-title-frame" aria-hidden="true">
                <AppIcon icon="title-icon-glyph stats-title-icon fa-solid fa-chart-column" />
              </span>
              <h2>数据统计</h2>
            </div>
            <div class="stats-grid">
              <div v-for="item in stats" :key="item.label" class="stat-item">
                <span>{{ item.label }}</span>
                <strong :class="item.tone">{{ item.value }}</strong>
              </div>
            </div>
          </section>

          <section class="guide-card panel sprig-corner guide-corner">
            <!-- 右上角插画使用裁剪后的独立图片，避免伪元素负偏移造成遮挡。 -->
            <img class="corner-image guide-corner-image" src="/assets/watercolor-leaf-branch-b.png" alt="" />
            <div class="section-title">
              <span class="title-icon guide-title-frame" aria-hidden="true">
                <AppIcon icon="title-icon-glyph guide-title-icon fa-regular fa-bookmark" />
              </span>
              <h2>使用须知</h2>
            </div>
            <div class="notice info">
              <h3>操作说明</h3>
              <ul>
                <li v-for="tip in usageTips" :key="tip">{{ tip }}</li>
              </ul>
            </div>
            <div class="notice warning">
              <h3>合规提示</h3>
              <ul>
                <li v-for="tip in complianceTips" :key="tip">{{ tip }}</li>
              </ul>
            </div>
          </section>

          <section class="env-card panel">
            <div class="section-title title-with-pill">
              <span class="title-icon env-title-frame" aria-hidden="true">
                <span class="title-icon-glyph env-title-icon"></span>
              </span>
              <h2>运行环境</h2>
            </div>
            <div class="env-grid">
              <div v-for="item in envItems" :key="item.name" class="env-item">
                <AppIcon :icon="['env-icon', item.icon]" />
                <strong>{{ item.name }}</strong>
                <small>{{ item.value }}</small>
              </div>
            </div>
          </section>
        </aside>

        <section class="log-card panel" aria-label="运行日志">
          <!-- 运行日志插画贴右下角显示，和日志内容保持清晰层级。 -->
          <img class="corner-image log-corner-image" src="/assets/watercolor-flower-branch.png" alt="" />
          <div class="log-header">
            <div class="section-title">
              <AppIcon icon="title-icon fa-regular fa-rectangle-list" />
              <h2>运行日志</h2>
            </div>
            <div class="log-tabs" aria-label="日志筛选">
              <button
                v-for="tab in logTabs"
                :key="tab.level"
                :class="['log-tab', `log-tab-${tab.level.toLowerCase()}`, { active: activeLogLevel === tab.level }]"
                type="button"
                @click="selectLogLevel(tab.level)"
              >
                {{ tab.label }}
              </button>
            </div>
            <div class="log-actions">
              <button type="button" @click="handleOpenLogFolder">
                <AppIcon icon="fa-regular fa-folder-open" /> Open Log Folder
              </button>
            </div>
          </div>
          <DynamicScroller
            ref="logScrollerRef"
            tabindex="0"
            class="log-table"
            :items="logDisplayRows"
            key-field="id"
            :min-item-size="24"
            @scroll.passive="handleLogTableScroll"
            @pointerdown.passive="markLogScrollUserInteraction"
            @touchstart.passive="markLogScrollUserInteraction"
            @wheel.passive="markLogScrollUserInteraction"
            @keydown="markLogScrollUserInteraction"
          >
            <template #default="{ item: row, index, active }">
              <DynamicScrollerItem
                :item="row"
                :active="active"
                :data-index="index"
                :size-dependencies="[row.message, row.levelLabel]"
              >
                <div :class="['log-row', `log-row-${row.levelClass}`]">
                  <time>[{{ row.time }}]</time>
                  <strong :class="['log-level', `log-level-${row.levelClass}`]">{{ row.levelLabel }}</strong>
                  <span class="log-message" :title="row.message">
                    <template v-for="(segment, segmentIndex) in row.messageSegments" :key="`${row.id}-${segmentIndex}`">
                      <span
                        v-if="segment.type === 'url'"
                        class="log-url"
                        :title="segment.fullText"
                      >{{ segment.text }}</span>
                      <span v-else>{{ segment.text }}</span>
                    </template>
                  </span>
                </div>
              </DynamicScrollerItem>
            </template>
            <template #empty>
              <div class="log-empty">
                暂无运行日志，程序开始运行后会实时显示最新信息。
              </div>
            </template>
          </DynamicScroller>
        </section>
        </template>

        <DataFilesPage v-else-if="activePage === 'files'" class="management-area" :summary-stats="stats" />
        <HistoryPage v-else-if="activePage === 'history'" class="management-area" />
        <SettingsPage
          v-else
          class="management-area"
          :environment-items="envItems"
          :task-status="taskStatus"
          @task-status-changed="handleTaskStatusChanged"
        />
      </div>
    </section>
    <TopbarHealthDialog
      :visible="healthDialogVisible"
      :title="`${healthDialogMeta.label}检测`"
      :icon="healthDialogMeta.icon"
      :tone="healthDialogState.tone"
      :status-label="healthDialogState.value"
      :message="healthDialogState.message"
      :items="healthDialogState.items"
      :checked-at="healthDialogState.checkedAt"
      :checking="healthDialogState.checking"
      @close="healthDialogVisible = false"
    />
    <TopbarHealthDialog
      :visible="startupSelfCheckDialogVisible"
      title="启动自检"
      icon="fa-solid fa-list-check"
      :tone="startupSelfCheckDialogState.tone"
      :status-label="startupSelfCheckDialogState.value"
      :message="startupSelfCheckDialogState.message"
      :items="startupSelfCheckDialogState.items"
      :checked-at="startupSelfCheckDialogState.checkedAt"
      :checking="startupSelfCheckDialogState.checking"
      @close="startupSelfCheckDialogVisible = false"
    />
    <div
      v-if="descriptionTooltip.visible"
      id="description-tooltip"
      class="description-tooltip"
      :style="{ left: `${descriptionTooltip.x}px`, top: `${descriptionTooltip.y}px` }"
      role="tooltip"
    >
      {{ descriptionTooltip.text }}
    </div>
    </main>
  </AConfigProvider>
</template>

<style scoped>
@font-face {
  font-family: 'HarmonyOS Sans SC';
  src: url('./assets/fonts/HarmonyOS_Sans_SC_Regular.ttf') format('truetype');
  font-display: swap;
  font-style: normal;
  font-weight: 400;
}

@font-face {
  font-family: 'HarmonyOS Sans SC';
  src: url('./assets/fonts/HarmonyOS_Sans_SC_Medium.ttf') format('truetype');
  font-display: swap;
  font-style: normal;
  font-weight: 500;
}

:global(*) {
  box-sizing: border-box;
}

:global(body) {
  margin: 0;
  min-width: 320px;
  color: var(--ink);
  background: var(--page);
  font-family:
    'HarmonyOS Sans SC', 'Microsoft YaHei', 'PingFang SC', 'Segoe UI', system-ui, -apple-system,
    BlinkMacSystemFont, sans-serif;
  font-synthesis-weight: none;
}

:global(html),
:global(body),
:global(#app) {
  width: 100%;
  height: 100%;
  overflow: hidden;
}

button,
input {
  font: inherit;
}

button {
  cursor: pointer;
}

button:focus-visible,
input:focus-visible {
  outline: 3px solid rgba(48, 113, 204, 0.32);
  outline-offset: 3px;
}

.collector-app {
  --page: #eaf3fb;
  --paper: #fbfdff;
  --paper-soft: #f3f8fc;
  --frost-bg: rgba(252, 254, 255, 0.66);
  --frost-bg-strong: rgba(252, 254, 255, 0.78);
  --frost-bg-soft: rgba(241, 249, 252, 0.46);
  --frost-border: rgba(102, 145, 184, 0.32);
  --frost-highlight: rgba(255, 255, 255, 0.84);
  --frost-inner: rgba(89, 132, 174, 0.08);
  --frost-shadow: rgba(35, 69, 111, 0.12);
  --frost-blur: blur(18px) saturate(1.34);
  --paper-texture-opacity: 0.045;
  --paper-card-texture-opacity: 0.045;
  --paper-edge: rgba(102, 145, 184, 0.26);
  --paper-shadow-sm: 0 1px 2px rgba(28, 55, 82, 0.06);
  --paper-shadow-md: 0 4px 9px rgba(28, 55, 82, 0.06), 0 8px 14px rgba(28, 55, 82, 0.045);
  --paper-hover-shadow: 0 5px 10px rgba(28, 55, 82, 0.075), 0 10px 15px rgba(28, 55, 82, 0.05);
  --paper-fiber:
    radial-gradient(circle at 14% 18%, rgba(28, 55, 82, 0.2) 0 0.6px, transparent 0.9px),
    radial-gradient(circle at 82% 64%, rgba(28, 55, 82, 0.16) 0 0.5px, transparent 0.85px),
    radial-gradient(circle at 38% 78%, rgba(28, 55, 82, 0.1) 0 0.45px, transparent 0.8px),
    radial-gradient(circle at 66% 28%, rgba(255, 255, 255, 0.42) 0 0.55px, transparent 0.9px),
    linear-gradient(92deg, rgba(28, 55, 82, 0.14), transparent 34%, rgba(28, 55, 82, 0.1) 66%, transparent),
    linear-gradient(178deg, transparent 0%, rgba(28, 55, 82, 0.08) 48%, transparent 100%);
  --ink: #15386f;
  --ink-strong: #0c2d63;
  --ink-muted: #4d6c9f;
  --line: rgba(104, 141, 181, 0.3);
  --line-soft: rgba(104, 141, 181, 0.18);
  --blue: #2d75d6;
  --green: #1f8f69;
  --green-soft: #dff3e8;
  --red: #d9413f;
  --orange: #df7a35;
  --purple: #6651cc;
  --teal-wash: rgba(121, 182, 185, 0.28);
  --design-width: 1600;
  --design-height: 900;
  --app-scale: min(
    calc(100vw / (var(--design-width) * 1px)),
    calc(100vh / (var(--design-height) * 1px))
  );
  display: flex;
  justify-content: center;
  align-items: flex-start;
  width: 100vw;
  height: 100vh;
  padding: 0;
  overflow: hidden;
  color: var(--ink);
  position: relative;
  isolation: isolate;
  background:
    radial-gradient(circle at 7% 6%, rgba(255, 255, 255, 0.96), transparent 24%),
    radial-gradient(circle at 94% 18%, rgba(210, 230, 246, 0.64), transparent 30%),
    linear-gradient(135deg, #f9fcff 0%, #eef6fd 54%, #f8fcff 100%);
}

.collector-app::before {
  content: '';
  position: fixed;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  opacity: var(--paper-texture-opacity);
  background: var(--paper-fiber);
  mix-blend-mode: multiply;
}

.collector-app.dark {
  --page: #0f1726;
  --paper: #151f31;
  --paper-soft: #111a2b;
  --frost-bg: rgba(22, 32, 50, 0.9);
  --frost-bg-strong: rgba(25, 37, 58, 0.96);
  --frost-bg-soft: rgba(16, 25, 41, 0.86);
  --frost-border: rgba(128, 153, 188, 0.2);
  --frost-highlight: rgba(214, 226, 244, 0.055);
  --frost-inner: rgba(123, 149, 184, 0.055);
  --frost-shadow: rgba(0, 0, 0, 0.2);
  --frost-blur: blur(10px) saturate(1.04);
  --paper-texture-opacity: 0.024;
  --paper-card-texture-opacity: 0.022;
  --paper-edge: rgba(128, 153, 188, 0.18);
  --paper-shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.16);
  --paper-shadow-md: 0 4px 9px rgba(0, 0, 0, 0.18), 0 8px 14px rgba(0, 0, 0, 0.16);
  --paper-hover-shadow: 0 5px 10px rgba(0, 0, 0, 0.22), 0 10px 15px rgba(0, 0, 0, 0.18);
  --paper-fiber:
    radial-gradient(circle at 14% 18%, rgba(214, 226, 244, 0.2) 0 0.6px, transparent 0.9px),
    radial-gradient(circle at 82% 64%, rgba(214, 226, 244, 0.14) 0 0.5px, transparent 0.85px),
    radial-gradient(circle at 38% 78%, rgba(214, 226, 244, 0.1) 0 0.45px, transparent 0.8px),
    linear-gradient(92deg, rgba(214, 226, 244, 0.12), transparent 34%, rgba(214, 226, 244, 0.08) 66%, transparent);
  --ink: #cbd8ea;
  --ink-strong: #e6eef8;
  --ink-muted: #8ea2bd;
  --line: rgba(128, 153, 188, 0.2);
  --line-soft: rgba(128, 153, 188, 0.1);
  --green-soft: rgba(64, 142, 111, 0.16);
  background:
    radial-gradient(circle at 8% 0%, rgba(53, 87, 135, 0.16), transparent 32%),
    radial-gradient(circle at 92% 12%, rgba(69, 89, 124, 0.12), transparent 34%),
    linear-gradient(135deg, #0d1421 0%, #111b2c 52%, #0e1726 100%);
}

.collector-app.dark::before {
  opacity: var(--paper-texture-opacity);
  background: var(--paper-fiber);
  mix-blend-mode: screen;
}

.workspace {
  position: relative;
  z-index: 1;
  width: 1600px;
  height: 900px;
  padding: 14px 16px;
  flex: 0 0 auto;
  transform: scale(var(--app-scale));
  transform-origin: top center;
  overflow: hidden;
}

.dark .sidebar-book,
.dark .corner-image {
  opacity: 0.3;
  mix-blend-mode: normal;
  filter: saturate(0.62) brightness(0.72) contrast(0.88);
}

.dark .sidebar-book {
  opacity: 0.24;
}

.dashboard {
  --section-gap: 14px;
  display: grid;
  grid-template-columns: 240px 430px 450px 400px;
  grid-template-rows: 462px 278px;
  grid-template-areas:
    'sidebar tasks status right'
    'sidebar logs logs right';
  gap: var(--section-gap) 16px;
  align-items: start;
  height: 754px;
}

.panel {
  position: relative;
  isolation: isolate;
  border: 1px solid var(--paper-edge);
  border-radius: 8px;
  background: var(--frost-bg-strong);
  box-shadow: var(--paper-shadow-sm), var(--paper-shadow-md);
  overflow: hidden;
}

.panel::before {
  content: '';
  position: absolute;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  background: var(--paper-fiber);
  opacity: var(--paper-card-texture-opacity);
}

.panel > * {
  position: relative;
  z-index: 1;
}

.dark .panel {
  border-color: var(--paper-edge);
  background: var(--frost-bg-strong);
  box-shadow: var(--paper-shadow-sm), var(--paper-shadow-md);
}

.dark .panel::before {
  background: var(--paper-fiber);
  opacity: var(--paper-card-texture-opacity);
}

.sidebar {
  grid-area: sidebar;
  position: relative;
  height: 754px;
  padding: 30px 20px 18px;
}

.nav-group {
  position: relative;
  z-index: 2;
}

.nav-group + .nav-group {
  margin-top: 32px;
  padding-top: 28px;
  border-top: 1px dashed var(--line);
}

.nav-title {
  margin: 0 0 18px 12px;
  color: var(--ink-strong);
  font-size: 18px;
  font-weight: 500;
}

.nav-title span {
  color: var(--green);
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 16px;
  width: 100%;
  min-height: 54px;
  margin-bottom: 12px;
  padding: 0 18px;
  border: 0;
  border-radius: 999px;
  color: var(--ink);
  background: transparent;
  font-size: 18px;
  font-weight: 500;
  text-align: left;
  text-decoration: none;
}

.nav-item:hover {
  background: rgba(74, 129, 183, 0.08);
}

.nav-item:disabled {
  cursor: not-allowed;
  opacity: 0.58;
}

.nav-item.active {
  color: #ffffff;
  background:
    radial-gradient(circle at 20% 10%, #ffffff4d, transparent 36%),
    linear-gradient(135deg, #5bbdc5eb, #2b8ea6eb);
  box-shadow: var(--paper-shadow-sm), inset 0 1px 0 rgba(255, 255, 255, 0.18);
}

.dark .nav-item.active {
  color: #eef6ff;
  background: #2b7f92;
}

.nav-icon {
  display: inline-grid;
  place-items: center;
  width: 32px;
  color: currentColor;
  font-size: 24px;
  line-height: 1;
}

.sidebar-book {
  position: absolute;
  left: 0;
  right: 0;
  bottom: -2px;
  z-index: 1;
  width: 100%;
  height: auto;
  object-fit: contain;
  object-position: center bottom;
  opacity: 0.72;
  pointer-events: none;
  mix-blend-mode: multiply;
  filter: saturate(0.92) contrast(0.96);
}

.task-column {
  grid-area: tasks;
  display: grid;
  gap: var(--section-gap);
}

.status-column {
  grid-area: status;
}

.right-column {
  grid-area: right;
  display: grid;
  grid-template-rows: 170px 376px 180px;
  gap: var(--section-gap);
  height: 754px;
}

.management-area {
  grid-column: 2 / 5;
  grid-row: 1 / 3;
  min-width: 0;
}

.task-card {
  display: grid;
  grid-template-columns: 118px minmax(0, 1fr);
  gap: 16px;
  height: 182px;
  padding: 18px 20px 16px;
}

.task-card-content {
  grid-template-columns: 118px minmax(0, 1fr);
  gap: 16px;
}

.task-volume-body {
  align-self: stretch;
  display: grid;
  grid-template-rows: auto auto auto auto;
  align-content: center;
  gap: 4px;
  min-width: 0;
}

.task-volume-row {
  display: grid;
  grid-template-columns: 64px minmax(0, 1fr);
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.task-control-label {
  color: var(--ink-strong);
  font-size: 14px;
  font-weight: 500;
  line-height: 1.25;
  white-space: nowrap;
}

.task-date-filter-trigger {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  min-width: 0;
  height: 34px;
  padding: 0 10px;
  border-color: var(--paper-edge);
  border-radius: 6px;
  color: var(--ink-strong);
  background: var(--frost-bg-strong);
  box-shadow: var(--paper-shadow-sm);
  font-size: 14px;
  font-weight: 400;
  text-align: left;
}

.task-date-filter-chevron {
  flex: 0 0 auto;
  color: var(--ink-muted);
  font-size: 10px;
}

.task-count-control {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 7px;
  min-width: 0;
}

.task-card-volume .number-stepper {
  flex: 1 1 148px;
  min-width: 0;
  max-width: 148px;
  height: 34px;
  grid-template-columns: 32px minmax(0, 1fr) 32px;
}

.task-card-volume .number-stepper button {
  width: 32px;
  font-size: 18px;
}

.task-count-hint {
  display: grid;
  place-items: center;
  flex: 0 0 27px;
  width: 27px;
  height: 27px;
  padding: 0;
  border: 0;
  border-radius: 50%;
  color: #397fa8;
  background: rgba(80, 143, 180, 0.1);
  font-size: 14px;
  cursor: help;
}

.task-count-hint:hover,
.task-count-hint:focus-visible {
  color: #286b94;
  background: rgba(80, 143, 180, 0.17);
}

.task-count-hint:focus-visible {
  outline: 2px solid rgba(57, 127, 168, 0.24);
  outline-offset: 2px;
}

.task-date-row {
  position: relative;
  grid-template-columns: minmax(0, 1fr);
  width: 100%;
  transform: translateY(4px);
}

.task-date-row > .task-control-label {
  position: absolute;
  top: 50%;
  right: calc(100% + 12px);
  transform: translateY(-50%);
}

.task-date-control {
  display: block;
  width: 100%;
  min-width: 0;
  height: 34px;
}

.task-date-picker {
  width: 100%;
  height: 34px;
}

.task-date-control :deep(.ant-picker) {
  width: 100%;
  height: 34px;
  border-color: var(--paper-edge);
  border-radius: 6px;
  background: var(--frost-bg-strong);
  box-shadow: var(--paper-shadow-sm);
}

.task-date-control :deep(.ant-picker-input > input) {
  color: var(--ink-strong);
  font-size: 14px;
}

.task-date-control :deep(.ant-picker-input > input::placeholder) {
  color: var(--ink-muted);
  opacity: 1;
}

.task-date-control :deep(.ant-picker-range .ant-picker-input) {
  flex: 1 1 0;
  min-width: 0;
}

.task-date-control :deep(.ant-picker-range-separator) {
  display: grid;
  place-items: center;
  flex: 0 0 28px;
  padding: 0;
}

.dark .task-count-hint {
  color: #9bbbd7;
  background: rgba(105, 153, 197, 0.12);
}

:global(.task-date-filter-dropdown .ant-dropdown-menu) {
  min-width: 180px;
  padding: 4px;
  border-radius: 6px;
}

:global(.task-date-filter-dropdown .ant-dropdown-menu-item) {
  min-height: 32px;
  font-size: 14px;
}

.step-badge {
  position: absolute;
  top: 16px;
  left: 22px;
  z-index: 1;
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border-radius: 50%;
  color: #ffffff;
  background:
    radial-gradient(circle at 28% 20%, rgba(255, 255, 255, 0.5), transparent 35%),
    linear-gradient(135deg, #88bfd7, #508fb4);
  font-size: 21px;
  font-weight: 500;
}

.dark .step-badge {
  color: #e3edf8;
  background:
    radial-gradient(circle at 28% 20%, rgba(232, 242, 255, 0.18), transparent 35%),
    linear-gradient(135deg, #4479a0, #315d86);
  box-shadow:
    inset 0 1px 0 rgba(232, 242, 255, 0.16),
    0 0 10px rgba(61, 120, 177, 0.12);
}

.task-art {
  align-self: center;
  justify-self: center;
  width: 112px;
  height: 112px;
  margin-top: 24px;
  object-fit: contain;
  pointer-events: none;
}

.task-art-list {
  transform: translate(20px, -5px);
}

.dark .task-art {
  opacity: 0.66;
  filter: saturate(0.64) brightness(0.76) contrast(0.9);
}

.task-art-heart {
  width: 108px;
  height: 108px;
}

.task-art-column {
  align-self: stretch;
  justify-self: center;
  display: grid;
  grid-template-rows: auto auto;
  align-content: end;
  justify-items: center;
  gap: 0;
  width: 100%;
  min-width: 0;
}

.task-card-content .task-art {
  align-self: end;
  margin-top: 0;
}

.task-card-content .task-art-heart {
  width: 112px;
  height: 112px;
  transform: translate(-14px, 12px);
}

.task-body {
  align-self: center;
  min-width: 0;
}

.task-body h2,
.task-volume-body h2,
.section-title h2 {
  margin: 0;
  color: var(--ink-strong);
  font-size: 22px;
  line-height: 1.2;
  font-weight: 500;
}

.task-body p {
  margin: 12px 0 0;
  color: var(--ink);
  font-size: 15px;
  font-weight: 400;
}

.task-body-content {
  display: grid;
  align-content: start;
  gap: 10px;
  padding-top: 1px;
}

.field-row {
  display: grid;
  grid-template-columns: 1fr;
  gap: 10px;
  align-items: start;
  margin-top: 18px;
  color: var(--ink);
  font-weight: 400;
}

.field-row label {
  line-height: 1.2;
}

.number-stepper {
  justify-self: end;
  display: grid;
  grid-template-columns: 36px 1fr 36px;
  min-width: 148px;
  max-width: 244px;
  height: 40px;
  border: 1px solid var(--paper-edge);
  border-radius: 6px;
  background: var(--frost-bg-strong);
  box-shadow: var(--paper-shadow-sm);
  overflow: hidden;
}

.dark .number-stepper {
  border-color: var(--paper-edge);
  background: var(--frost-bg-strong);
  box-shadow: var(--paper-shadow-sm);
}

.dark .number-stepper button {
  color: #9db1cc;
  background: rgba(28, 43, 65, 0.46);
}

.dark .number-stepper input {
  color: #e1eaf6;
  background: rgba(10, 18, 30, 0.28);
}

.number-stepper button,
.number-stepper input {
  min-width: 0;
  border: 0;
  color: var(--ink);
  background: transparent;
  text-align: center;
}

.number-stepper button {
  display: grid;
  place-items: center;
  width: 36px;
  color: var(--ink-muted);
  font-size: 20px;
  font-weight: 400;
}

.number-stepper input {
  width: 100%;
  border-left: 1px solid var(--line);
  border-right: 1px solid var(--line);
  color: var(--ink-strong);
  font-weight: 400;
  outline: 0;
}

.number-stepper button:disabled,
.number-stepper input:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.number-stepper input::-webkit-outer-spin-button,
.number-stepper input::-webkit-inner-spin-button {
  margin: 0;
  appearance: none;
  -webkit-appearance: none;
}

.download-options {
  justify-self: end;
  display: grid;
  gap: 7px;
  width: min(100%, 190px);
}

.download-option {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  min-height: 32px;
  padding: 5px 10px;
  border: 1px solid rgba(104, 141, 181, 0.2);
  border-radius: 9px;
  color: var(--ink);
  background: var(--frost-bg-strong);
  box-shadow: var(--paper-shadow-sm);
  text-align: left;
  font-size: 14px;
  font-weight: 400;
}

.download-option:hover {
  background: rgba(233, 246, 247, 0.58);
}

.download-option.locked {
  border-color: rgba(111, 130, 155, 0.22);
  color: rgba(77, 108, 159, 0.74);
  background: rgba(230, 237, 245, 0.58);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.5);
  cursor: not-allowed;
}

.article-detail-option {
  width: 184px;
  min-height: 32px;
  padding-inline: 10px;
}

.task-date-label {
  justify-content: flex-start;
  gap: 8px;
  width: 120px;
  height: 34px;
  min-height: 34px;
  padding-inline: 10px;
  border-radius: 6px;
  cursor: default;
  pointer-events: none;
}

.task-date-label-spin {
  flex: 0 0 14px;
  width: 14px;
  height: 14px;
  color: rgba(77, 108, 159, 0.82);
  line-height: 1;
}

.dark .task-date-label-spin {
  color: rgba(153, 183, 219, 0.86);
}

.download-option.locked:hover {
  background: rgba(230, 237, 245, 0.58);
}

.download-option.selected {
  border-color: rgba(48, 132, 128, 0.32);
  color: var(--ink-strong);
  background: rgba(219, 241, 235, 0.64);
}

.download-option.selected.locked {
  border-color: rgba(111, 130, 155, 0.24);
  color: rgba(69, 91, 124, 0.78);
  background: rgba(230, 237, 245, 0.68);
}

.option-box {
  display: grid;
  place-items: center;
  width: 17px;
  height: 17px;
  flex: 0 0 auto;
  border: 1px solid rgba(77, 108, 159, 0.42);
  border-radius: 5px;
  color: transparent;
  background: rgba(255, 255, 255, 0.5);
}

.download-option.selected .option-box {
  border-color: rgba(31, 143, 105, 0.4);
  color: #ffffff;
  background: linear-gradient(135deg, rgba(86, 159, 145, 0.92), rgba(50, 132, 126, 0.9));
}

.download-option.selected.locked .option-box {
  border-color: rgba(111, 130, 155, 0.34);
  color: #ffffff;
  background: linear-gradient(135deg, rgba(122, 139, 162, 0.86), rgba(93, 112, 139, 0.84));
}

.option-box i {
  font-size: 10px;
}

.dark .download-option {
  border-color: rgba(117, 148, 187, 0.22);
  color: #b9c8dd;
  background: rgba(17, 27, 44, 0.66);
  box-shadow: inset 0 1px 0 rgba(214, 226, 244, 0.04);
}

.dark .download-option:hover {
  background: rgba(24, 38, 60, 0.78);
}

.dark .download-option.locked,
.dark .download-option.locked:hover {
  border-color: rgba(117, 148, 187, 0.16);
  color: rgba(154, 171, 196, 0.62);
  background: rgba(24, 34, 50, 0.52);
}

.dark .download-option.selected {
  border-color: rgba(95, 151, 180, 0.36);
  color: #d7e7f2;
  background: rgba(35, 66, 84, 0.72);
}

.dark .download-option.selected.locked {
  border-color: rgba(117, 148, 187, 0.2);
  color: rgba(178, 190, 210, 0.68);
  background: rgba(31, 43, 59, 0.62);
}

.dark .option-box {
  border-color: rgba(130, 158, 194, 0.34);
  background: rgba(10, 18, 30, 0.52);
}

.dark .download-option.selected .option-box {
  border-color: rgba(102, 163, 184, 0.42);
  background: linear-gradient(135deg, rgba(63, 127, 151, 0.92), rgba(45, 101, 132, 0.9));
}

.dark .download-option.selected.locked .option-box {
  border-color: rgba(117, 148, 187, 0.26);
  background: linear-gradient(135deg, rgba(85, 101, 123, 0.76), rgba(65, 82, 105, 0.74));
}

.control-panel {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px;
  height: 70px;
  padding: 10px 18px;
}

.run-button,
.stop-button {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 14px;
  min-height: 50px;
  border: 1px solid rgba(49, 92, 92, 0.18);
  border-radius: 14px;
  color: #ffffff;
  font-size: 20px;
  font-weight: 500;
  overflow: hidden;
  box-shadow: var(--paper-shadow-sm), var(--paper-shadow-md);
  text-shadow: none;
  transition:
    transform 160ms ease,
    filter 160ms ease,
    box-shadow 160ms ease,
    border-color 160ms ease;
}

.run-button::before,
.stop-button::before {
  display: none;
}

.run-button::after,
.stop-button::after {
  content: '';
  position: absolute;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  background: var(--paper-fiber);
  mix-blend-mode: soft-light;
  opacity: 0.08;
}

.run-button i,
.stop-button i,
.button-label {
  position: relative;
  z-index: 1;
}

.run-button i,
.stop-button i {
  width: 18px;
  font-size: 17px;
  text-align: center;
}

.run-button {
  isolation: isolate;
}

.stop-button {
  isolation: isolate;
}

.run-button:hover,
.stop-button:hover {
  filter: brightness(1.03) saturate(1.02);
  transform: translateY(-1px);
  border-color: rgba(49, 92, 92, 0.24);
  box-shadow: var(--paper-shadow-sm), var(--paper-hover-shadow);
}

.run-button:disabled,
.stop-button:disabled {
  cursor: not-allowed;
  pointer-events: none;
  opacity: 0.46;
  filter: grayscale(0.72) saturate(0.55);
  transform: none;
  border-color: rgba(112, 130, 155, 0.2);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.36),
    0 2px 5px rgba(35, 69, 111, 0.06);
  text-shadow: none;
}

.run-button:disabled:hover,
.stop-button:disabled:hover,
.run-button:disabled:active,
.stop-button:disabled:active {
  filter: grayscale(0.72) saturate(0.55);
  transform: none;
  border-color: rgba(112, 130, 155, 0.2);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.36),
    0 2px 5px rgba(35, 69, 111, 0.06);
}

.run-button:active,
.stop-button:active {
  filter: brightness(0.98);
  transform: translateY(1px);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.4),
    inset 0 2px 7px rgba(35, 69, 111, 0.11),
    0 4px 8px rgba(38, 70, 116, 0.08);
}

.run-button {
  background: #4aae9f;
}

.stop-button {
  background: #c9655f;
}

.dark .run-button,
.dark .stop-button {
  border-color: rgba(142, 174, 210, 0.28);
  box-shadow: var(--paper-shadow-sm), var(--paper-shadow-md);
  text-shadow: none;
}

.dark .run-button {
  background: #2f8d82;
}

.dark .stop-button {
  background: #864f53;
}

.dark .run-button::after,
.dark .stop-button::after {
  opacity: 0.08;
  mix-blend-mode: normal;
  background: var(--paper-fiber);
}

.dark .run-button:hover,
.dark .stop-button:hover {
  filter: brightness(1.03) saturate(1.02);
  border-color: rgba(153, 188, 225, 0.36);
  box-shadow:
    inset 0 1px 0 rgba(232, 242, 255, 0.12),
    0 0 0 1px rgba(67, 116, 184, 0.1),
    0 7px 12px rgba(0, 0, 0, 0.18);
}

.dark .run-button:disabled,
.dark .stop-button:disabled {
  opacity: 0.52;
  color: #8f9db1;
  border-color: rgba(117, 148, 187, 0.16);
  background: rgba(38, 46, 61, 0.78);
  box-shadow:
    inset 0 1px 0 rgba(232, 242, 255, 0.045),
    0 2px 5px rgba(0, 0, 0, 0.12);
}

.dark .run-button:disabled:hover,
.dark .stop-button:disabled:hover,
.dark .run-button:disabled:active,
.dark .stop-button:disabled:active {
  border-color: rgba(117, 148, 187, 0.16);
  box-shadow:
    inset 0 1px 0 rgba(232, 242, 255, 0.045),
    0 2px 5px rgba(0, 0, 0, 0.12);
}

.status-card {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  height: 462px;
  padding: 20px 16px 18px;
}

.corner-image {
  position: absolute;
  opacity: 0.68;
  pointer-events: none;
  object-fit: contain;
  z-index: 1;
  mix-blend-mode: multiply;
  filter: saturate(0.9) contrast(0.95);
}

.status-corner-image,
.stats-corner-image,
.guide-corner-image {
  top: 0;
  right: 0;
  height: auto;
  object-position: top right;
}

.status-corner-image {
  width: 172px;
}

.stats-corner-image {
  width: 118px;
}

.guide-corner-image {
  width: 122px;
}

.section-title {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.title-icon {
  display: inline-grid;
  place-items: center;
  width: 30px;
  height: 30px;
  flex: 0 0 auto;
  color: var(--blue);
  font-size: 22px;
  line-height: 1;
}

.stats-card .title-icon,
.guide-card .title-icon,
.env-card .title-icon {
  display: inline-grid;
  place-items: center;
  width: 34px;
  height: 34px;
  flex: 0 0 34px;
  line-height: 1;
}

.title-icon-glyph {
  display: block;
  color: var(--blue);
  line-height: 1;
}

.stats-title-icon {
  width: 30px;
  height: 30px;
  font-size: 30px;
}

.guide-title-icon {
  width: 31px;
  height: 31px;
  font-size: 31px;
  transform: translateY(1px);
}

.env-title-icon {
  width: 31px;
  height: 31px;
  background: var(--blue);
  -webkit-mask: url('/assets/computer-solid-full.svg') center / contain no-repeat;
  mask: url('/assets/computer-solid-full.svg') center / contain no-repeat;
}

.status-title-logo {
  display: block;
  width: 38px;
  height: 30px;
}

.status-list {
  display: grid;
  align-content: space-between;
  gap: 12px;
  min-height: 0;
  margin-top: 18px;
  padding-bottom: 18px;
  border-bottom: 1px dashed var(--line);
}

.status-row {
  display: grid;
  grid-template-columns: 18px 96px minmax(0, 1fr);
  gap: 6px;
  align-items: center;
  min-width: 0;
  color: var(--ink);
  font-size: 14px;
}

.status-row.with-progress {
  grid-template-columns: 18px 96px minmax(0, 1fr) max-content;
}

.row-icon {
  width: 18px;
  color: var(--blue);
  font-size: 14px;
  line-height: 1;
  text-align: center;
}

.status-label {
  color: var(--ink-muted);
  font-weight: 400;
  white-space: nowrap;
}

.status-row strong {
  color: var(--ink-strong);
  font-weight: 500;
}

.status-value {
  min-width: 0;
  width: 100%;
}

.status-value-ellipsis {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status-value.status-description-value {
  cursor: help;
}

.status-description-value:focus-visible {
  outline: 3px solid rgba(45, 117, 214, 0.22);
  outline-offset: 2px;
  border-radius: 5px;
}

.status-pill {
  justify-self: start;
  padding: 3px 8px;
  border-radius: 6px;
  color: var(--green);
  background: var(--green-soft);
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
}

.status-pill.orange {
  color: #b46b18;
  background: rgba(255, 236, 190, 0.72);
}

.status-pill.blue {
  color: #1d63bd;
  background: rgba(222, 237, 255, 0.78);
}

.status-pill.red {
  color: #b92f32;
  background: rgba(255, 226, 226, 0.78);
}

.status-pill.purple {
  color: #5f46c4;
  background: rgba(235, 230, 255, 0.78);
}

.progress-line {
  height: 8px;
  border-radius: 999px;
  background: rgba(116, 137, 168, 0.2);
  overflow: hidden;
}

.progress-line span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #2b8a72, #6eb7d3);
}

.status-row em {
  color: var(--ink-muted);
  font-style: normal;
  font-weight: 500;
  white-space: nowrap;
}

.description-tooltip {
  position: fixed;
  z-index: 50;
  max-width: min(360px, calc(100vw - 24px));
  padding: 9px 11px;
  border: 1px solid rgba(104, 141, 181, 0.32);
  border-radius: 8px;
  color: var(--ink-strong);
  background: rgba(251, 253, 255, 0.96);
  box-shadow: 0 8px 18px rgba(38, 70, 116, 0.16);
  font-size: 13px;
  font-weight: 400;
  line-height: 1.55;
  pointer-events: none;
  white-space: normal;
  word-break: break-word;
}

.dark .description-tooltip {
  color: var(--ink-strong);
  background: rgba(18, 28, 45, 0.96);
  border-color: rgba(128, 153, 188, 0.22);
}

.network-panel {
  display: grid;
  grid-template-columns: 118px minmax(0, 94px) minmax(116px, 1fr);
  gap: 16px;
  align-items: center;
  min-height: 82px;
  padding-top: 18px;
}

.network-panel p {
  margin: 0 0 7px;
  color: var(--ink-muted);
  font-size: 14px;
  font-weight: 400;
}

.network-panel strong {
  display: inline-flex;
  line-height: 1.2;
  font-size: 15px;
  white-space: nowrap;
}

.speed-upload {
  color: var(--green);
}

.speed-download {
  color: var(--blue);
}

.speed {
  display: contents;
}

.speed p {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  color: var(--ink-muted);
  font-size: 14px;
  font-weight: 400;
  white-space: nowrap;
}

.speed-icon {
  width: 18px;
  color: var(--blue);
  font-size: 15px;
  text-align: center;
}

.speed-values {
  display: grid;
  gap: 9px;
  align-items: center;
  justify-items: start;
  min-width: 0;
  white-space: nowrap;
}

.mini-chart {
  align-self: center;
  width: 100%;
  min-width: 116px;
  height: 62px;
}

.stats-card,
.guide-card,
.env-card {
  padding: 18px 24px;
}

.stats-card {
  --blue: #2378d7;
  --green: #168a78;
  --purple: #6d56d7;
  height: 100%;
  padding-top: 16px;
  padding-bottom: 14px;
}

.stats-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px 24px;
  margin-top: 8px;
}

.stat-item {
  display: grid;
  gap: 3px;
  min-height: 40px;
}

.stat-item:nth-child(odd) {
  border-right: 1px dashed var(--line);
}

.stat-item span {
  color: var(--ink-muted);
  font-size: 15px;
  font-weight: 400;
}

.stat-item strong {
  color: var(--blue);
  font-size: 23px;
  line-height: 1.1;
  font-weight: 400;
}

.guide-card {
  display: grid;
  gap: 12px;
  height: 100%;
}

.notice {
  padding: 12px 16px;
  border: 1px solid rgba(104, 141, 181, 0.2);
  border-radius: 8px;
  box-shadow: var(--paper-shadow-sm);
}

.notice.info {
  margin-top: 6px;
  background: rgba(225, 240, 250, 0.58);
}

.notice.warning {
  background: rgba(255, 239, 219, 0.6);
}

.notice h3 {
  margin: 0 0 6px;
  color: var(--blue);
  font-size: 16px;
}

.notice.warning h3 {
  color: var(--orange);
}

.notice ul {
  margin: 0;
  padding-left: 20px;
  color: var(--ink);
  line-height: 1.56;
  font-size: 14px;
  font-weight: 400;
}

.dark .notice {
  border-color: rgba(117, 148, 187, 0.18);
  box-shadow: var(--paper-shadow-sm);
}

.dark .notice.info {
  background: rgba(23, 45, 68, 0.68);
}

.dark .notice.warning {
  background: rgba(70, 57, 48, 0.62);
}

.dark .notice h3 {
  color: #76aef4;
}

.dark .notice.warning h3 {
  color: #d79a5e;
}

.dark .notice ul {
  color: #c3d0e2;
}

.title-with-pill {
  justify-content: flex-start;
}

.env-card {
  height: 100%;
  padding: 14px 18px;
}

.env-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin-top: 12px;
}

.env-item {
  display: grid;
  grid-template-columns: 20px minmax(0, 1fr);
  gap: 2px 5px;
  min-height: 54px;
  min-width: 0;
  padding: 8px 6px;
  border: 1px solid rgba(104, 141, 181, 0.18);
  border-radius: 6px;
  background: var(--frost-bg-strong);
  box-shadow: var(--paper-shadow-sm);
}

.dark .env-item {
  background: var(--frost-bg-strong);
  box-shadow: var(--paper-shadow-sm);
}

.env-icon {
  grid-row: 1 / 3;
  align-self: center;
  color: var(--blue);
  font-size: 17px;
  line-height: 1;
  text-align: center;
}

.env-item strong {
  min-width: 0;
  color: var(--ink-strong);
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
}

.env-item small {
  min-width: 0;
  color: var(--ink-muted);
  font-size: 11.5px;
  font-weight: 500;
  white-space: nowrap;
}

.log-card {
  grid-area: logs;
  height: 278px;
  padding: 18px 22px;
}

.log-card::after {
  content: none;
}

.log-corner-image {
  right: 0;
  bottom: 0;
  z-index: 0;
  width: 268px;
  height: auto;
  opacity: 0.46;
  object-position: right bottom;
}

.dark .log-corner-image {
  opacity: 0.3;
}

.log-header {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 18px;
  align-items: center;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--line);
}

.log-tabs,
.log-actions {
  display: flex;
  align-items: center;
  gap: 16px;
  min-width: 0;
}

.log-tabs button,
.log-actions button {
  border: 0;
  color: var(--ink);
  background: transparent;
  font-size: 13px;
  font-weight: 400;
  white-space: nowrap;
}

.log-actions i {
  width: 14px;
  margin-right: 4px;
  text-align: center;
}

.log-tabs button.active {
  color: var(--blue);
  border-bottom: 2px solid var(--blue);
}

.log-actions {
  justify-content: flex-end;
}

.log-table {
  position: relative;
  z-index: 1;
  box-sizing: border-box;
  height: 200px;
  margin-top: 8px;
  padding: 8px 10px;
  border: 1px solid rgba(104, 141, 181, 0.2);
  border-radius: 8px;
  background: rgba(252, 254, 255, 0.56);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.62);
  overflow: auto;
  scrollbar-gutter: stable;
}

.dark .log-table {
  border-color: rgba(128, 153, 188, 0.18);
  background: rgba(15, 24, 39, 0.44);
  box-shadow: inset 0 1px 0 rgba(214, 226, 244, 0.045);
}

.log-table :deep(.vue-recycle-scroller__item-view) {
  box-sizing: border-box;
  padding-right: 2px;
}

.log-row {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: 78px 58px minmax(0, 1fr);
  gap: 8px;
  min-height: 24px;
  align-items: start;
  color: var(--ink);
  font-size: 14px;
  text-shadow: none;
  filter: none;
}

.log-row time,
.log-row strong {
  padding-top: 2px;
}

.log-row time {
  color: var(--ink-muted);
}

.log-level {
  color: var(--ink);
  font-weight: 400;
}

.log-level-info {
  color: var(--ink);
}

.log-message {
  min-width: 0;
  max-width: 100%;
  opacity: 1;
  filter: none;
  line-height: 1.45;
  text-shadow: none;
  white-space: normal;
  overflow: hidden;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.log-url {
  display: block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: bottom;
  white-space: nowrap;
}

.log-row-info .log-message {
  color: var(--ink);
}

.log-level-success,
.log-row-success .log-message {
  color: #16a15d;
}

.log-level-warn,
.log-row-warn .log-message {
  color: var(--orange);
}

.log-level-error,
.log-row-error .log-message {
  color: var(--red);
}

.log-empty {
  padding: 26px 0;
  color: var(--ink-muted);
  font-size: 14px;
  font-weight: 400;
  text-align: center;
}

.sprig-corner::after {
  content: none;
}

.blue {
  color: var(--blue) !important;
}

.green {
  color: var(--green) !important;
}

.red {
  color: var(--red) !important;
}

.purple {
  color: var(--purple) !important;
}

.orange {
  color: var(--orange) !important;
}

@supports not ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
  .panel,
  .number-stepper,
  .notice,
  .env-item {
    background: var(--paper);
  }
}

@media (prefers-reduced-transparency: reduce) {
  .panel,
  .number-stepper,
  .notice,
  .env-item {
    background: var(--paper);
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    transition-duration: 0.01ms !important;
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
  }
}

</style>
