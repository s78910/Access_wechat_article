<script setup lang="ts">
import AppIcon from '../components/AppIcon.vue'
import type { VxeGridPropTypes } from 'vxe-table'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  getHistoryRecords,
  getHistorySuggestions,
  getHistorySummary,
  type HistoryRecordItem,
  type HistorySummary,
} from '../bridge/pythonApi'
import type { MetricCard } from '../data/mockData'
import {
  buildHistorySuggestionOptions,
  createHistorySuggestionRemoteConfig,
  type HistorySuggestionQuery,
} from '../utils/historySuggestions'

type HistoryRecord = HistoryRecordItem

const HISTORY_VISIBLE_ROWS = 15
const HISTORY_TABLE_HEADER_HEIGHT = 32
const DEFAULT_HISTORY_TABLE_BODY_HEIGHT = 480
const HISTORY_QUERY_DEBOUNCE_MS = 250

const keyword = ref('')
const selectedCollectType = ref('')
const selectedStatus = ref('')
const selectedCollectStartDate = ref('')
const selectedCollectEndDate = ref('')
const historyCurrentPage = ref(1)
const historyPageSize = ref(HISTORY_VISIBLE_ROWS)
const historyPagerLayouts: Array<'PrevPage' | 'JumpNumber' | 'NextPage'> = ['PrevPage', 'JumpNumber', 'NextPage']
const selectedHistoryId = ref<number | null>(null)
const historyRecords = ref<HistoryRecord[]>([])
const historyTotal = ref(0)
const historyLoading = ref(false)
const historyError = ref('')
const historySummary = ref<HistorySummary | null>(null)
const summaryLoading = ref(false)
const historySuggestions = ref<string[]>([])
const historyTableWrapRef = ref<HTMLElement | null>(null)
const historyTableBodyHeight = ref(DEFAULT_HISTORY_TABLE_BODY_HEIGHT)
let historyTableResizeObserver: ResizeObserver | null = null
let historyRecordsDebounceTimer: ReturnType<typeof setTimeout> | null = null
let historySuggestionsDebounceTimer: ReturnType<typeof setTimeout> | null = null
let historyRecordsRequestId = 0
let historySuggestionsRequestId = 0

// 表格固定 15 行展示，行高由分页上方的剩余空间反推；向下取值避免 15 行累计后产生内部滚动。
const historyRowHeight = computed(() => Math.floor((historyTableBodyHeight.value / HISTORY_VISIBLE_ROWS) * 100) / 100)
const historyGridStyle = computed<Record<string, string>>(() => ({
  '--history-row-height': `${historyRowHeight.value}px`,
  '--history-body-height': `${historyTableBodyHeight.value}px`,
}))

type PagerChangeParams = {
  currentPage: number
  pageSize: number
}

const collectTypeOptions = [
  { label: '全部类型', value: '' },
  { label: '文章详情', value: '文章详情' },
  { label: '评论信息', value: '评论信息' },
]

const statusOptions = [
  { label: '全部状态', value: '' },
  { label: '成功', value: 'success' },
  { label: '失败', value: 'failed' },
]

const historyMetrics = computed<MetricCard[]>(() => {
  const summary = historySummary.value
  return [
    {
      label: '历史任务数',
      value: String(summary?.totalRecords ?? 0),
      icon: 'fa-regular fa-clipboard',
      tone: 'blue',
      hint: '来自 awa_fetch_history',
    },
    {
      label: '成功率',
      value: `${summary?.successRate ?? 0}%`,
      icon: 'fa-solid fa-check',
      tone: 'green',
      hint: 'success / 全部任务',
    },
    {
      label: '最近采集日期',
      value: summary?.latestCollectDate || '-',
      icon: 'fa-regular fa-calendar-days',
      tone: 'blue',
      hint: '按 started_time 统计',
    },
    {
      label: '累计采集文章',
      value: String(summary?.collectedArticleCount ?? 0),
      icon: 'fa-regular fa-file-lines',
      tone: 'orange',
      hint: '成功文章按 ID 去重',
    },
  ]
})

const chartBars = computed(() => historySummary.value?.trend.map((item) => item.count) ?? [])
const chartLabels = computed(() => historySummary.value?.trend.map((item) => item.label) ?? [])
const chartMaxValue = computed(() => Math.max(1, ...chartBars.value))

// 根据采集结果文本统一映射状态色，避免表格和详情里的状态样式各写一套判断。
function getStatusTone(status: string) {
  if (status === '成功') {
    return 'success'
  }

  if (status === '失败') {
    return 'danger'
  }

  if (status === '部分完成') {
    return 'warning'
  }

  return 'neutral'
}

// 采集记录只展示开始采集时间，保留标准 HH:mm:ss，便于和真实采集日志对照。
const historyNameOptions = computed(() => {
  return buildHistorySuggestionOptions(historySuggestions.value)
})

function truncateAccountName(account: string) {
  const chars = Array.from(account || '')
  return chars.length > 10 ? `${chars.slice(0, 9).join('')}...` : account
}

const pagedHistoryRecords = computed(() => historyRecords.value)

const historySeqConfig = computed(() => {
  return {
    startIndex: (historyCurrentPage.value - 1) * historyPageSize.value,
  }
})

const historyColumns: VxeGridPropTypes.Columns<HistoryRecord> = [
  { type: 'seq', title: '序号', width: 48, align: 'center', headerAlign: 'center' },
  {
    field: 'name',
    title: '记录名称',
    width: 200,
    align: 'left',
    headerAlign: 'center',
    showOverflow: 'ellipsis',
    slots: { default: 'name' },
  },
  {
    field: 'account',
    title: '公众号',
    width: 128,
    align: 'center',
    headerAlign: 'center',
    slots: { default: 'account' },
  },
  { field: 'collectType', title: '采集类型', width: 72, align: 'center', headerAlign: 'center' },
  { field: 'collectTime', title: '记录时间', width: 168, align: 'center', headerAlign: 'center' },
  {
    field: 'status',
    title: '状态',
    width: 82,
    align: 'center',
    headerAlign: 'center',
    className: 'history-status-column',
    slots: { default: 'status' },
  },
  {
    title: '操作',
    width: 52,
    align: 'center',
    headerAlign: 'center',
    slots: { default: 'action' },
  },
]

const selectedHistoryRecord = computed(() => {
  if (!selectedHistoryId.value) {
    return null
  }

  return historyRecords.value.find((row) => row.id === selectedHistoryId.value) ?? null
})

const recordDetail = computed(() => {
  const record = selectedHistoryRecord.value

  if (!record) {
    return null
  }

  return {
    name: record.name,
    account: record.account,
    collectType: record.collectType,
    startedTime: record.startedTime,
    finishedTime: record.finishedTime,
    publishedArticleTime: record.publishedArticleTime,
    articleLink: record.articleLink,
    duration: record.duration,
    status: record.status,
    collectStatus: record.collectStatus,
    resourceTypeLabels: record.resourceTypeLabels,
    outputDir: record.outputDir,
    errorStageLabel: record.errorStageLabel,
    errorMessage: record.errorMessage,
  }
})

async function loadHistorySummary() {
  summaryLoading.value = true
  try {
    historySummary.value = await getHistorySummary()
  } catch (error) {
    // 汇总失败不阻断列表和候选加载，页面用空指标明确降级。
    historySummary.value = null
  } finally {
    summaryLoading.value = false
  }
}

async function loadHistorySuggestions(query: Partial<HistorySuggestionQuery> = {}) {
  const requestId = ++historySuggestionsRequestId
  try {
    const result = await getHistorySuggestions({
      keyword: query.keyword ?? keyword.value,
      limit: query.limit ?? 30,
    })
    if (requestId !== historySuggestionsRequestId) {
      return
    }
    historySuggestions.value = result.items
  } catch {
    if (requestId !== historySuggestionsRequestId) {
      return
    }
    // 候选只影响输入提示，失败时保留空列表，不阻断历史记录查询。
    historySuggestions.value = []
  }
}

function scheduleHistorySuggestionsLoad(query: Partial<HistorySuggestionQuery> = {}) {
  if (historySuggestionsDebounceTimer) {
    clearTimeout(historySuggestionsDebounceTimer)
  }
  historySuggestionsDebounceTimer = setTimeout(() => {
    historySuggestionsDebounceTimer = null
    void loadHistorySuggestions(query)
  }, HISTORY_QUERY_DEBOUNCE_MS)
}

const historySuggestionRemoteConfig = createHistorySuggestionRemoteConfig(scheduleHistorySuggestionsLoad)

function updateHistoryTableMetrics() {
  const tableWrap = historyTableWrapRef.value

  if (!tableWrap) {
    return
  }

  const nextBodyHeight = tableWrap.clientHeight - HISTORY_TABLE_HEADER_HEIGHT

  if (nextBodyHeight <= 0) {
    return
  }

  historyTableBodyHeight.value = Number(nextBodyHeight.toFixed(2))
}

async function loadHistoryRecords(page = historyCurrentPage.value, pageSize = historyPageSize.value) {
  const requestId = ++historyRecordsRequestId
  historyLoading.value = true
  historyError.value = ''
  try {
    const result = await getHistoryRecords({
      page,
      pageSize,
      keyword: keyword.value,
      collectType: selectedCollectType.value,
      status: selectedStatus.value,
      collectStartDate: selectedCollectStartDate.value,
      collectEndDate: selectedCollectEndDate.value,
    })
    if (requestId !== historyRecordsRequestId) {
      return
    }
    historyCurrentPage.value = result.page
    historyPageSize.value = result.pageSize
    historyTotal.value = result.total
    historyRecords.value = result.items
    if (selectedHistoryId.value && !result.items.some((item) => item.id === selectedHistoryId.value)) {
      selectedHistoryId.value = null
    }
  } catch (error) {
    if (requestId !== historyRecordsRequestId) {
      return
    }
    historyError.value = error instanceof Error ? error.message : '读取采集记录失败'
    historyRecords.value = []
    historyTotal.value = 0
  } finally {
    if (requestId === historyRecordsRequestId) {
      historyLoading.value = false
    }
  }
}

function scheduleHistoryRecordsLoad() {
  if (historyRecordsDebounceTimer) {
    clearTimeout(historyRecordsDebounceTimer)
  }
  historyRecordsDebounceTimer = setTimeout(() => {
    historyRecordsDebounceTimer = null
    void loadHistoryRecords(1, historyPageSize.value)
  }, HISTORY_QUERY_DEBOUNCE_MS)
}

function clearHistoryQueryTimers() {
  if (historyRecordsDebounceTimer) {
    clearTimeout(historyRecordsDebounceTimer)
    historyRecordsDebounceTimer = null
  }
  if (historySuggestionsDebounceTimer) {
    clearTimeout(historySuggestionsDebounceTimer)
    historySuggestionsDebounceTimer = null
  }
}

async function resetHistoryFilters() {
  clearHistoryQueryTimers()
  keyword.value = ''
  selectedCollectType.value = ''
  selectedStatus.value = ''
  selectedCollectStartDate.value = ''
  selectedCollectEndDate.value = ''
  historyCurrentPage.value = 1
  await Promise.all([loadHistorySummary(), loadHistorySuggestions(), loadHistoryRecords(1, historyPageSize.value)])
}

function selectHistoryRecord(row: HistoryRecord) {
  selectedHistoryId.value = row.id
}

async function handleHistoryPageChange({ currentPage, pageSize }: PagerChangeParams) {
  historyCurrentPage.value = currentPage
  historyPageSize.value = pageSize
  await loadHistoryRecords(currentPage, pageSize)
}

watch(keyword, () => {
  historyCurrentPage.value = 1
  scheduleHistoryRecordsLoad()
  scheduleHistorySuggestionsLoad()
})

watch([selectedCollectType, selectedStatus, selectedCollectStartDate, selectedCollectEndDate], async () => {
  historyCurrentPage.value = 1
  await loadHistoryRecords(1, historyPageSize.value)
})

onMounted(async () => {
  await Promise.all([loadHistorySummary(), loadHistorySuggestions(), loadHistoryRecords(1, historyPageSize.value)])
  await nextTick()
  updateHistoryTableMetrics()

  if (typeof ResizeObserver !== 'undefined' && historyTableWrapRef.value) {
    historyTableResizeObserver = new ResizeObserver(updateHistoryTableMetrics)
    historyTableResizeObserver.observe(historyTableWrapRef.value)
  }
})

onBeforeUnmount(() => {
  clearHistoryQueryTimers()
  historyRecordsRequestId += 1
  historySuggestionsRequestId += 1
  historyTableResizeObserver?.disconnect()
})
</script>

<template>
  <section class="management-page history-page" aria-label="采集历史">
    <div class="metric-grid history-metrics config-summary-metrics">
      <article v-for="item in historyMetrics" :key="item.label" class="metric-card page-panel">
        <span :class="['metric-icon', item.tone]">
          <AppIcon :icon="item.icon" />
        </span>
        <div class="metric-body">
          <span>{{ item.label }}</span>
          <strong :class="item.tone">{{ item.value }}</strong>
        </div>
      </article>
    </div>

    <section class="history-list page-panel" aria-label="采集记录">
      <div class="history-list-header">
        <h2 class="section-heading">
          <AppIcon icon="fa-regular fa-rectangle-list" />
          采集记录
        </h2>

        <div class="filters-row history-filters">
          <VxeSelect
            v-model="keyword"
            class="history-vxe-control history-keyword"
            clearable
            filterable
            remote
            placeholder="搜索记录"
            :options="historyNameOptions"
            :option-props="{ label: 'label', value: 'value' }"
            :remote-config="historySuggestionRemoteConfig"
            :popup-config="{ transfer: true, zIndex: 3000, className: 'history-keyword-panel' }"
            aria-label="搜索记录"
          />
          <VxeSelect
            v-model="selectedCollectType"
            class="history-vxe-control"
            :options="collectTypeOptions"
            :popup-config="{ transfer: true, zIndex: 3000, className: 'history-filter-select-panel' }"
            aria-label="采集类型"
          />
          <VxeSelect
            v-model="selectedStatus"
            class="history-vxe-control"
            :options="statusOptions"
            :popup-config="{ transfer: true, zIndex: 3000, className: 'history-filter-select-panel' }"
            aria-label="任务状态"
          />
          <VxeDateRangePicker
            v-model:start-value="selectedCollectStartDate"
            v-model:end-value="selectedCollectEndDate"
            class="history-vxe-control history-date-range-picker"
            type="date"
            clearable
            auto-close
            placeholder="采集起始 ~ 结束日期"
            separator=" ~ "
            value-format="yyyy-MM-dd"
            label-format="yyyy-MM-dd"
            :popup-config="{ transfer: true, zIndex: 3000, className: 'history-date-range-picker-panel' }"
            aria-label="采集起始日期和采集结束日期"
          />
          <VxeButton class="history-vxe-button ghost" type="button" @click="resetHistoryFilters">
            <AppIcon icon="fa-solid fa-rotate-right" />
            刷新
          </VxeButton>
        </div>
      </div>

      <div ref="historyTableWrapRef" class="history-vxe-table-wrap">
        <VxeGrid
          class="history-vxe-grid"
          :style="historyGridStyle"
          :columns="historyColumns"
          :data="pagedHistoryRecords"
          height="100%"
          :row-config="{ keyField: 'id' }"
          :seq-config="historySeqConfig"
          :cell-config="{ height: historyRowHeight }"
          :fit="false"
          :scroll-x="{ enabled: false }"
          :scroll-y="{ enabled: false }"
          :show-overflow="true"
          :show-header-overflow="true"
          border="inner"
          size="mini"
        >
          <template #name="{ row }: { row: HistoryRecord }">
            <span class="history-title-cell" :title="row.name">{{ row.name }}</span>
          </template>
          <template #account="{ row }: { row: HistoryRecord }">
            <span class="history-account-cell" :title="row.account">{{ truncateAccountName(row.account) }}</span>
          </template>
          <template #status="{ row }: { row: HistoryRecord }">
            <span
              :class="[
                'status-badge',
                `status-${getStatusTone(row.status)}`,
              ]"
            >
              {{ row.status }}
            </span>
          </template>
          <template #action="{ row }: { row: HistoryRecord }">
            <VxeButton class="history-view-link" mode="text" status="primary" @click="selectHistoryRecord(row)">
              查看
            </VxeButton>
          </template>
          <template #empty>
            <div :class="['history-table-state', { error: Boolean(historyError) }]">
              <span v-if="historyLoading">正在读取采集记录...</span>
              <span v-else-if="historyError">{{ historyError }}</span>
              <span v-else>暂无采集记录</span>
            </div>
          </template>
        </VxeGrid>
      </div>

      <div class="history-vxe-pagination" aria-label="采集历史分页">
        <span class="history-total">共 {{ historyTotal }} 条</span>
        <VxePager
          v-model:current-page="historyCurrentPage"
          v-model:page-size="historyPageSize"
          class-name="history-vxe-pager"
          size="mini"
          align="right"
          :layouts="historyPagerLayouts"
          :pager-count="7"
          :page-sizes="[15]"
          :total="historyTotal"
          @page-change="handleHistoryPageChange"
        >
          <template #right>
            <span class="history-page-size">{{ historyPageSize }}条/页</span>
          </template>
        </VxePager>
      </div>
    </section>

    <aside class="history-side">
      <section class="task-detail page-panel">
        <img class="panel-corner-art detail-art" src="/assets/watercolor-leaf-branch-b.png" alt="" />
        <h2 class="section-heading">
          <AppIcon icon="fa-regular fa-file-lines" />
          记录详情
        </h2>
        <div v-if="recordDetail" class="detail-list">
          <div class="detail-row">
            <span>公众号名</span>
            <strong>{{ recordDetail.account }}</strong>
          </div>
          <div class="detail-row">
            <span>记录名称</span>
            <strong>{{ recordDetail.name }}</strong>
          </div>
          <div class="detail-row">
            <span>文章发布时间</span>
            <strong>{{ recordDetail.publishedArticleTime || '-' }}</strong>
          </div>
          <div class="detail-row">
            <span>开始时间</span>
            <strong>{{ recordDetail.startedTime || '-' }}</strong>
          </div>
          <div class="detail-row">
            <span>结束时间</span>
            <strong>{{ recordDetail.finishedTime || '-' }}</strong>
          </div>
          <div class="detail-row">
            <span>采集类型</span>
            <strong>{{ recordDetail.collectType }}</strong>
          </div>
          <div class="detail-row">
            <span>执行时长</span>
            <strong>{{ recordDetail.duration }}</strong>
          </div>
          <div class="detail-row">
            <span>文章链接</span>
            <strong class="detail-value-wrap" :title="recordDetail.articleLink">
              {{ recordDetail.articleLink || '-' }}
            </strong>
          </div>
          <div class="detail-row">
            <span>运行结果</span>
            <strong>
              <span
                :class="[
                  'status-badge',
                  `status-${getStatusTone(recordDetail.status)}`,
                ]"
              >
                {{ recordDetail.status }}
              </span>
            </strong>
          </div>
          <template v-if="recordDetail.collectStatus === 'failed'">
            <div class="detail-row">
              <span>失败阶段</span>
              <strong>{{ recordDetail.errorStageLabel || '-' }}</strong>
            </div>
            <div class="detail-row">
              <span>失败原因</span>
              <strong class="detail-value-wrap">{{ recordDetail.errorMessage || '未记录具体原因' }}</strong>
            </div>
          </template>
          <template v-else>
            <div class="detail-row">
              <span>资源类型</span>
              <strong class="detail-value-wrap">
                {{ recordDetail.resourceTypeLabels.join('、') || '-' }}
              </strong>
            </div>
            <div class="detail-row">
              <span>输出目录</span>
              <strong class="detail-value-wrap" :title="recordDetail.outputDir">
                {{ recordDetail.outputDir || '-' }}
              </strong>
            </div>
          </template>
        </div>
        <div v-else class="detail-empty">
          <AppIcon icon="fa-regular fa-hand-pointer" />
          <strong>点击左侧“查看”</strong>
          <span>选择一条采集记录后，这里会显示文章标题、公众号、采集类型、采集时间、执行时长和记录内容。</span>
        </div>
      </section>

      <section class="history-stats page-panel">
        <h2 class="section-heading">
          <AppIcon icon="fa-solid fa-chart-column" />
          历史统计
        </h2>
        <p class="chart-caption">近日采集趋势</p>
        <div class="trend-chart" aria-label="近日采集趋势">
          <div v-for="(bar, index) in chartBars" :key="chartLabels[index]" class="trend-item">
            <VxeTooltip
              :content="`${chartLabels[index]}：${bar} 条`"
              placement="top"
              theme="light"
              :enter-delay="80"
            >
              <span
                class="trend-bar"
                :style="{ height: `${Math.round((bar / chartMaxValue) * 92)}px` }"
              ></span>
            </VxeTooltip>
            <small>{{ chartLabels[index] }}</small>
          </div>
        </div>
        <div class="summary-grid">
          <div>
            <AppIcon icon="fa-solid fa-check" />
            <strong>{{ historySummary?.successfulRecords ?? 0 }}</strong>
            <span>成功记录</span>
          </div>
          <div>
            <AppIcon icon="fa-solid fa-xmark" />
            <strong>{{ historySummary?.failedRecords ?? 0 }}</strong>
            <span>失败记录</span>
          </div>
          <div>
            <AppIcon icon="fa-regular fa-clock" />
            <strong>{{ summaryLoading ? '读取中' : (historySummary?.averageDuration ?? '00:00.00') }}</strong>
            <span>平均耗时</span>
          </div>
        </div>
      </section>
    </aside>
  </section>
</template>

<style scoped>
.history-page {
  height: 100%;
  grid-template-columns: minmax(0, 1fr) 420px;
  grid-template-rows: 72px minmax(0, 1fr);
  grid-template-areas:
    'metrics metrics'
    'list side';
}

.history-metrics {
  grid-area: metrics;
}

.history-list {
  grid-area: list;
  display: flex;
  flex-direction: column;
  min-height: 0;
  padding: 16px 20px 8px;
}

.history-list-header {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  align-items: center;
  gap: 24px;
  min-height: 48px;
  min-width: 0;
}

.history-list-header .section-heading {
  margin: 0;
  white-space: nowrap;
}

.history-side {
  grid-area: side;
  display: grid;
  /* 右侧总高度跟主内容行一致，第二块吃掉剩余空间，避免底部超出左侧列表。 */
  grid-template-rows: 348px minmax(0, 1fr);
  gap: 14px;
  min-height: 0;
  min-width: 0;
}

.task-detail,
.history-stats,
.history-log {
  padding: 18px 24px;
}

.history-filters {
  grid-template-columns: minmax(136px, 156px) minmax(92px, 104px) minmax(92px, 104px) minmax(188px, 1fr) 76px;
  justify-self: end;
  position: relative;
  z-index: 8;
  width: min(100%, 660px);
  gap: 10px;
  margin-top: 0;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}

.history-vxe-control {
  width: 100%;
  min-width: 0;
}

.history-keyword {
  min-width: 0;
}

.history-list :deep(.history-keyword .vxe-input--suffix) {
  width: 28px;
  flex-basis: 28px;
  padding-right: 6px;
  box-sizing: border-box;
}

.history-list :deep(.history-keyword .vxe-input--inner) {
  padding-right: 8px;
}

.history-date-range-picker {
  min-width: 0;
}

.history-list :deep(.history-vxe-control.vxe-input),
.history-list :deep(.history-vxe-control.vxe-select),
.history-list :deep(.history-vxe-control.vxe-date-range-picker) {
  width: 100%;
  height: 38px;
  color: var(--ink);
  font-size: 14px;
  font-weight: 400;
}

.history-list :deep(.history-vxe-control .vxe-input--wrapper),
.history-list :deep(.history-vxe-control.vxe-select),
.history-list :deep(.history-vxe-control.vxe-date-range-picker) {
  border-color: var(--line);
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.48);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.6);
}

.history-list :deep(.history-vxe-control .vxe-input--inner),
.history-list :deep(.history-vxe-control .vxe-date-range-picker--inner),
.history-list :deep(.history-vxe-control .vxe-date-range-picker--prefix),
.history-list :deep(.history-vxe-control .vxe-date-range-picker--suffix) {
  color: var(--ink);
  font-size: 14px;
  font-weight: 400;
}

.history-list :deep(.history-vxe-control .vxe-input--inner::placeholder),
.history-list :deep(.history-vxe-control .vxe-date-range-picker--inner::placeholder) {
  color: rgba(77, 108, 159, 0.72);
  font-weight: 400;
}

.history-list :deep(.history-date-range-picker.vxe-date-range-picker) {
  height: 38px;
  border-color: var(--line);
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.48);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.6);
}

.history-list :deep(.history-date-range-picker .vxe-date-range-picker--prefix),
.history-list :deep(.history-date-range-picker .vxe-date-range-picker--suffix),
.history-list :deep(.history-date-range-picker .vxe-date-range-picker--inner) {
  background: transparent;
  text-align: center;
}

.history-list :deep(.history-date-range-picker .vxe-date-range-picker--inner) {
  text-align: center;
}

.history-list :deep(.history-date-range-picker .vxe-date-range-picker--inner::placeholder) {
  text-align: center;
}

:global(.history-keyword-panel.vxe-select--panel),
:global(.history-filter-select-panel.vxe-select--panel),
:global(.history-date-range-picker-panel.vxe-date-range-picker--panel) {
  color: var(--ink);
  font-size: 14px;
  font-weight: 400;
}

:global(.history-keyword-panel .vxe-select--panel-wrapper),
:global(.history-filter-select-panel .vxe-select--panel-wrapper) {
  border-color: var(--line);
  border-radius: 7px;
  background: #fbfdff;
  box-shadow: 0 12px 22px rgba(35, 69, 111, 0.14);
}

:global(.history-keyword-panel .vxe-select-option),
:global(.history-keyword-panel .vxe-select--empty-placeholder),
:global(.history-filter-select-panel .vxe-select-option),
:global(.history-filter-select-panel .vxe-select--empty-placeholder),
:global(.history-date-range-picker-panel .vxe-date-panel--picker-label),
:global(.history-date-range-picker-panel .vxe-date-panel--picker-btn),
:global(.history-date-range-picker-panel .vxe-date-panel--view-header),
:global(.history-date-range-picker-panel .vxe-date-panel--view-item-inner),
:global(.history-date-range-picker-panel .vxe-date-panel--label) {
  color: var(--ink);
  font-weight: 400;
}

:global(.history-keyword-panel .vxe-select-option.is--selected),
:global(.history-filter-select-panel .vxe-select-option.is--selected),
:global(.history-date-range-picker-panel .vxe-date-panel--picker-type-wrapper),
:global(.history-date-range-picker-panel .vxe-date-panel--picker-label) {
  color: var(--ink-strong);
  font-weight: 500;
}

.history-vxe-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 76px;
  height: 38px;
  border: 1px solid var(--line);
  border-radius: 6px;
  color: var(--ink);
  background: rgba(255, 255, 255, 0.5);
  box-shadow: var(--paper-shadow-sm);
  font-size: 14px;
  font-weight: 500;
}

.history-vxe-button.primary {
  color: #ffffff;
  border-color: rgba(45, 117, 214, 0.32);
  background: #2d75d6;
}

.history-vxe-button.ghost {
  color: var(--blue);
  background: rgba(255, 255, 255, 0.5);
}

.history-vxe-table-wrap {
  position: relative;
  --history-header-height: 32px;
  --history-body-height: 480px;
  flex: 1 1 0;
  height: auto;
  box-sizing: content-box;
  min-height: 0;
  margin-top: 6px;
  border: 1px solid rgba(104, 141, 181, 0.18);
  border-radius: 7px;
  background: rgba(255, 255, 255, 0.38);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.58);
  overflow: hidden;
}

.history-vxe-grid {
  --vxe-ui-font-color: var(--ink);
  --vxe-ui-font-primary-color: var(--blue);
  --vxe-ui-layout-background-color: rgba(255, 255, 255, 0.34);
  --vxe-ui-table-header-background-color: rgba(234, 244, 251, 0.54);
  --vxe-ui-table-border-color: var(--line-soft);
  --vxe-ui-table-row-hover-background-color: rgba(74, 129, 183, 0.08);
  --vxe-ui-table-row-height-mini: var(--history-row-height, 32px);
  --vxe-ui-table-cell-padding-mini: 4px;
  height: 100%;
  overflow: hidden;
}

.history-list :deep(.history-vxe-grid.vxe-grid) {
  color: var(--ink);
  background: transparent;
  font-size: 14px;
  font-weight: 400;
}

.history-list :deep(.history-vxe-grid .vxe-table) {
  color: var(--ink);
  background: transparent;
  overflow: hidden;
}

.history-list :deep(.history-vxe-grid .vxe-table--main-wrapper),
.history-list :deep(.history-vxe-grid .vxe-table--header-wrapper),
.history-list :deep(.history-vxe-grid .vxe-table--body-wrapper) {
  width: 100% !important;
}

.history-list :deep(.history-vxe-grid .vxe-table--main-wrapper) {
  height: 100% !important;
}

.history-list :deep(.history-vxe-grid .vxe-table--header-wrapper) {
  height: var(--history-header-height) !important;
  overflow: hidden !important;
}

.history-list :deep(.history-vxe-grid .vxe-table--body-wrapper) {
  height: var(--history-body-height) !important;
}

.history-list :deep(.history-vxe-grid .vxe-table--header),
.history-list :deep(.history-vxe-grid .vxe-table--body) {
  width: 100% !important;
}

.history-list :deep(.history-vxe-grid .vxe-table--header-border-line) {
  display: none;
}

.history-list :deep(.history-vxe-grid .vxe-table--body-wrapper) {
  overflow: hidden !important;
  scrollbar-width: none;
  -ms-overflow-style: none;
}

.history-list :deep(.history-vxe-grid .vxe-table--body-wrapper::-webkit-scrollbar) {
  width: 0;
  height: 0;
}

.history-list :deep(.history-vxe-grid .vxe-table--scroll-y-wrapper),
.history-list :deep(.history-vxe-grid .vxe-table--scroll-y-virtual-wrapper),
.history-list :deep(.history-vxe-grid .vxe-table--scroll-x-wrapper),
.history-list :deep(.history-vxe-grid .vxe-table--scroll-x-virtual-wrapper) {
  width: 0 !important;
  height: 0 !important;
  opacity: 0;
  pointer-events: none;
}

.history-list :deep(.history-vxe-grid .vxe-header--column) {
  height: var(--history-header-height) !important;
  color: var(--ink-strong);
  background: rgba(234, 244, 251, 0.48);
  font-size: 14px;
  font-weight: 500;
}

.history-list :deep(.history-vxe-grid .vxe-body--column) {
  height: var(--history-row-height, 32px) !important;
  color: var(--ink);
  font-size: 14px;
  font-weight: 400;
}

.history-list :deep(.history-vxe-grid .vxe-cell) {
  display: flex;
  align-items: center;
  min-height: var(--history-row-height, 32px);
  height: var(--history-row-height, 32px);
  padding: 0 4px !important;
  line-height: 1.2;
}

.history-list :deep(.history-vxe-grid .vxe-header--column .vxe-cell),
.history-list :deep(.history-vxe-grid .vxe-body--column.col--center .vxe-cell) {
  justify-content: center;
}

.history-list :deep(.history-vxe-grid .history-status-column .vxe-cell) {
  align-items: center;
  justify-content: center;
}

.history-list :deep(.history-vxe-grid .status-badge) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 70px;
  height: 24px;
  gap: 4px;
  padding: 0 7px;
  border: 1px solid transparent;
  font-size: 12px;
  line-height: 24px;
}

.history-list :deep(.history-vxe-grid .status-badge::before) {
  width: 5px;
  height: 5px;
}

.history-list :deep(.history-vxe-grid .status-badge.status-success),
.detail-row .status-badge.status-success {
  border-color: rgba(31, 143, 105, 0.16);
  color: var(--green);
  background: rgba(31, 143, 105, 0.14);
}

.history-list :deep(.history-vxe-grid .status-badge.status-warning),
.detail-row .status-badge.status-warning {
  border-color: rgba(223, 122, 53, 0.18);
  color: var(--orange);
  background: rgba(223, 122, 53, 0.15);
}

.history-list :deep(.history-vxe-grid .status-badge.status-danger),
.detail-row .status-badge.status-danger {
  border-color: rgba(217, 65, 63, 0.16);
  color: var(--red);
  background: rgba(217, 65, 63, 0.13);
}

.history-list :deep(.history-vxe-grid .status-badge.status-neutral),
.detail-row .status-badge.status-neutral {
  border-color: rgba(104, 141, 181, 0.18);
  color: var(--ink-muted);
  background: rgba(104, 141, 181, 0.12);
}

.history-title-cell {
  display: block;
  width: 100%;
  overflow: hidden;
  color: var(--ink-strong);
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.history-account-cell {
  display: block;
  max-width: 10em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.history-table-state {
  display: grid;
  place-items: center;
  min-height: 120px;
  color: var(--ink);
  font-size: 14px;
  font-weight: 500;
}

.history-table-state.error {
  color: var(--red);
}

.record-content-row {
  align-items: start;
}

.task-detail .detail-list {
  gap: 8px;
  margin-top: 14px;
}

.task-detail .detail-row {
  grid-template-columns: 82px minmax(0, 1fr);
  gap: 8px;
  font-size: 13px;
}

.task-detail .detail-row strong {
  min-width: 0;
  font-weight: 500;
}

.detail-value-wrap {
  overflow-wrap: anywhere;
  white-space: normal;
}

.detail-row .record-content {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
  overflow: visible;
  white-space: normal;
}

.record-content span {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 22px;
  padding: 0 6px;
  border: 1px solid rgba(104, 141, 181, 0.2);
  border-radius: 6px;
  color: var(--ink);
  background: rgba(255, 255, 255, 0.36);
  font-size: 11px;
  font-weight: 400;
}

.history-view-link {
  padding: 0 1px;
  color: var(--blue);
  font-size: 13px;
  font-weight: 500;
  line-height: 1.2;
}

.history-list :deep(.history-view-link.vxe-button.type--text.size--mini) {
  min-height: auto;
  padding: 0 1px;
  font-size: 13px;
  line-height: 1.2;
}

.history-list :deep(.history-view-link .vxe-button--content) {
  font-size: inherit;
  line-height: inherit;
}

.history-vxe-pagination {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  margin-top: 6px;
  min-height: 31px;
  color: var(--ink);
  font-size: 13px;
  font-weight: 400;
}

.history-total {
  flex: 0 0 auto;
  color: var(--ink);
  white-space: nowrap;
}

.history-list :deep(.history-vxe-pager.vxe-pager) {
  flex: 1 1 auto;
  min-width: 0;
  margin-left: auto;
  padding: 0;
  color: var(--ink);
  background: transparent;
  font-size: 13px;
  font-weight: 900;
}

.history-list :deep(.history-vxe-pager .vxe-pager--wrapper) {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
  width: 100%;
  min-height: 32px;
}

.history-list :deep(.history-vxe-pager .vxe-pager--prev-btn),
.history-list :deep(.history-vxe-pager .vxe-pager--next-btn),
.history-list :deep(.history-vxe-pager .vxe-pager--num-btn),
.history-list :deep(.history-vxe-pager .vxe-pager--jump-prev),
.history-list :deep(.history-vxe-pager .vxe-pager--jump-next) {
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

.history-list :deep(.history-vxe-pager .vxe-pager--prev-btn),
.history-list :deep(.history-vxe-pager .vxe-pager--next-btn) {
  width: 32px;
  padding: 0;
  color: rgba(77, 108, 159, 0.78);
}

.history-list :deep(.history-vxe-pager .vxe-pager--jump-prev),
.history-list :deep(.history-vxe-pager .vxe-pager--jump-next) {
  min-width: 24px;
  padding: 0 6px;
  color: rgba(77, 108, 159, 0.72);
}

.history-list :deep(.history-vxe-pager .vxe-pager--prev-btn:hover:not(.is--disabled)),
.history-list :deep(.history-vxe-pager .vxe-pager--next-btn:hover:not(.is--disabled)),
.history-list :deep(.history-vxe-pager .vxe-pager--num-btn:hover:not(.is--active)),
.history-list :deep(.history-vxe-pager .vxe-pager--jump-prev:hover:not(.is--disabled)),
.history-list :deep(.history-vxe-pager .vxe-pager--jump-next:hover:not(.is--disabled)) {
  border-color: rgba(45, 117, 214, 0.24);
  background: rgba(255, 255, 255, 0.86);
}

.history-list :deep(.history-vxe-pager .vxe-pager--num-btn.is--active) {
  color: #ffffff;
  border-color: rgba(45, 117, 214, 0.32);
  background: linear-gradient(135deg, #4d85dc, #2d70cc);
}

.history-list :deep(.history-vxe-pager .is--disabled) {
  cursor: not-allowed;
  color: rgba(77, 108, 159, 0.36);
  background: rgba(255, 255, 255, 0.46);
}

.history-list :deep(.history-vxe-pager .vxe-pager--btn-icon),
.history-list :deep(.history-vxe-pager .vxe-pager--jump-icon),
.history-list :deep(.history-vxe-pager .vxe-pager--jump-more-icon) {
  line-height: 1;
}

.history-list :deep(.history-vxe-pager .vxe-pager--right-wrapper) {
  display: inline-flex;
  align-items: center;
  margin-left: 2px;
}

.history-page-size {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 82px;
  height: 30px;
  padding: 0 12px;
  border: 1px solid var(--line);
  border-radius: 7px;
  color: var(--ink);
  background: rgba(255, 255, 255, 0.46);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.62);
  font-size: 13px;
  font-weight: 400;
  white-space: nowrap;
}

.detail-art {
  top: 0;
  right: 0;
  width: 118px;
}

.detail-empty {
  display: grid;
  justify-items: start;
  gap: 10px;
  margin-top: 28px;
  padding: 18px;
  border: 1px dashed rgba(104, 141, 181, 0.34);
  border-radius: 8px;
  color: var(--ink);
  background: rgba(255, 255, 255, 0.28);
}

.detail-empty i {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border-radius: 50%;
  color: #ffffff;
  background: linear-gradient(135deg, #74aefa, #2d75d6);
  font-size: 15px;
}

.detail-empty strong {
  color: var(--ink-strong);
  font-size: 15px;
  font-weight: 500;
}

.detail-empty span {
  color: var(--ink);
  line-height: 1.62;
  font-size: 13px;
  font-weight: 400;
}

.chart-caption {
  margin: 12px 0 6px;
  color: var(--ink);
  font-size: 14px;
  font-weight: 500;
}

.trend-chart {
  position: relative;
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  align-items: end;
  height: 112px;
  padding: 8px 10px 0;
}

.trend-item {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-end;
  gap: 7px;
  height: 100%;
}

.trend-bar {
  display: block;
  width: 24px;
  border-radius: 5px 5px 0 0;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.34), transparent 34%),
    linear-gradient(180deg, #79aee8, #2d75d6);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.48);
  transition:
    filter 150ms ease,
    transform 150ms ease;
}

.trend-bar:hover {
  filter: saturate(1.08) brightness(1.04);
  transform: translateY(-2px);
}

.trend-item small {
  line-height: 1;
  color: var(--ink);
  font-size: 12px;
  font-weight: 500;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin-top: 16px;
}

.summary-grid div {
  display: grid;
  justify-items: center;
  gap: 3px;
  min-height: 60px;
  padding: 8px 6px;
  border: 1px solid var(--line-soft);
  border-radius: 7px;
  background: rgba(255, 255, 255, 0.34);
  box-shadow: var(--paper-shadow-sm);
}

.summary-grid i {
  color: var(--green);
  font-size: 19px;
}

.summary-grid div:nth-child(2) i,
.summary-grid div:nth-child(2) strong {
  color: var(--red);
}

.summary-grid div:nth-child(3) i,
.summary-grid div:nth-child(3) strong {
  color: var(--blue);
}

.summary-grid strong {
  color: var(--green);
  font-size: 19px;
  font-weight: 500;
}

.summary-grid span {
  color: var(--ink);
  font-size: 12px;
  font-weight: 400;
}

.history-log {
  grid-area: log;
}

.log-art {
  right: 0;
  bottom: 0;
  width: 250px;
}

.log-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
}

.log-buttons {
  display: inline-flex;
  gap: 10px;
}

.history-log-table {
  display: grid;
  gap: 8px;
  margin-top: 14px;
}

.history-log-row {
  display: grid;
  grid-template-columns: 86px 70px minmax(0, 1fr);
  gap: 16px;
  color: var(--ink);
  font-size: 14px;
  font-weight: 700;
}

.history-log-row time,
.history-log-row strong {
  font-family: Consolas, 'SFMono-Regular', monospace;
}

.history-log-row time {
  color: var(--ink-muted);
}

.history-log-row strong {
  color: var(--green);
}

.history-log-row strong.warn {
  color: var(--orange);
}

.history-log-row strong.success {
  color: #16a15d;
}

.page-size {
  width: 96px;
  height: 32px;
}

:global(.collector-app.dark) .history-list :deep(.history-vxe-control .vxe-input--wrapper),
:global(.collector-app.dark) .history-list :deep(.history-vxe-control.vxe-select),
:global(.collector-app.dark) .history-list :deep(.history-vxe-control.vxe-date-range-picker) {
  border-color: rgba(128, 153, 188, 0.2);
  background: rgba(15, 24, 39, 0.62);
  box-shadow: inset 0 1px 0 rgba(214, 226, 244, 0.045);
}

:global(.collector-app.dark) .history-list :deep(.history-vxe-control .vxe-input--inner),
:global(.collector-app.dark) .history-list :deep(.history-vxe-control .vxe-date-range-picker--inner),
:global(.collector-app.dark) .history-list :deep(.history-vxe-control .vxe-date-range-picker--prefix),
:global(.collector-app.dark) .history-list :deep(.history-vxe-control .vxe-date-range-picker--suffix) {
  color: #cbd8ea;
}

:global(.collector-app.dark) .history-list :deep(.history-vxe-control .vxe-input--inner::placeholder),
:global(.collector-app.dark) .history-list :deep(.history-vxe-control .vxe-date-range-picker--inner::placeholder) {
  color: rgba(142, 162, 189, 0.72);
}

:global(.collector-app.dark) .history-list :deep(.history-date-range-picker.vxe-date-range-picker) {
  border-color: rgba(128, 153, 188, 0.2);
  background: rgba(15, 24, 39, 0.62);
  box-shadow: inset 0 1px 0 rgba(214, 226, 244, 0.045);
}

:global(.collector-app.dark) .history-vxe-button {
  color: #cbd8ea;
  border-color: rgba(128, 153, 188, 0.2);
  background: rgba(17, 27, 44, 0.72);
  box-shadow: inset 0 1px 0 rgba(214, 226, 244, 0.045);
}

:global(.collector-app.dark) .history-vxe-button.primary {
  color: #f0f6ff;
  border-color: rgba(111, 154, 211, 0.34);
  background: #2f6fb5;
}

:global(.collector-app.dark) .history-vxe-button.ghost {
  color: #8fbded;
  background: rgba(17, 27, 44, 0.62);
}

:global(.collector-app.dark) .history-vxe-table-wrap {
  border-color: rgba(128, 153, 188, 0.14);
  background: rgba(15, 24, 39, 0.52);
  box-shadow: inset 0 1px 0 rgba(214, 226, 244, 0.045);
}

:global(.collector-app.dark) .history-list :deep(.history-vxe-grid.vxe-grid),
:global(.collector-app.dark) .history-list :deep(.history-vxe-grid .vxe-table),
:global(.collector-app.dark) .history-list :deep(.history-vxe-grid .vxe-table--main-wrapper),
:global(.collector-app.dark) .history-list :deep(.history-vxe-grid .vxe-table--header-wrapper),
:global(.collector-app.dark) .history-list :deep(.history-vxe-grid .vxe-table--body-wrapper) {
  color: #c5d3e6;
  background: transparent;
}

:global(.collector-app.dark) .history-list :deep(.history-vxe-grid .vxe-header--column) {
  color: #dce7f5;
  background: rgba(24, 37, 58, 0.86);
}

:global(.collector-app.dark) .history-list :deep(.history-vxe-grid .vxe-body--column) {
  color: #c5d3e6;
  border-color: rgba(128, 153, 188, 0.1);
  background: transparent;
}

:global(.collector-app.dark) .history-list :deep(.history-vxe-grid .vxe-body--row:hover .vxe-body--column) {
  background: rgba(36, 56, 84, 0.32);
}

:global(.collector-app.dark) .history-title-cell,
:global(.collector-app.dark) .history-account-cell {
  color: #dce7f5;
}

:global(.collector-app.dark) .history-table-state,
:global(.collector-app.dark) .history-total,
:global(.collector-app.dark) .history-page-size {
  color: #8ea2bd;
}

:global(.collector-app.dark) .history-list :deep(.history-view-link.vxe-button.type--text.size--mini) {
  color: #8fbded;
}

:global(.collector-app.dark) .history-list :deep(.history-vxe-pager .vxe-pager--prev-btn),
:global(.collector-app.dark) .history-list :deep(.history-vxe-pager .vxe-pager--next-btn),
:global(.collector-app.dark) .history-list :deep(.history-vxe-pager .vxe-pager--num-btn),
:global(.collector-app.dark) .history-list :deep(.history-vxe-pager .vxe-pager--jump-prev),
:global(.collector-app.dark) .history-list :deep(.history-vxe-pager .vxe-pager--jump-next),
:global(.collector-app.dark) .history-page-size {
  color: #a9bfda;
  border-color: rgba(128, 153, 188, 0.16);
  background: rgba(17, 27, 44, 0.72);
  box-shadow: inset 0 1px 0 rgba(214, 226, 244, 0.04);
}

:global(.collector-app.dark) .history-list :deep(.history-vxe-pager .vxe-pager--prev-btn:hover:not(.is--disabled)),
:global(.collector-app.dark) .history-list :deep(.history-vxe-pager .vxe-pager--next-btn:hover:not(.is--disabled)),
:global(.collector-app.dark) .history-list :deep(.history-vxe-pager .vxe-pager--num-btn:hover:not(.is--active)),
:global(.collector-app.dark) .history-list :deep(.history-vxe-pager .vxe-pager--jump-prev:hover:not(.is--disabled)),
:global(.collector-app.dark) .history-list :deep(.history-vxe-pager .vxe-pager--jump-next:hover:not(.is--disabled)) {
  color: #dceaff;
  border-color: rgba(111, 154, 211, 0.34);
  background: rgba(24, 38, 60, 0.86);
}

:global(.collector-app.dark) .history-list :deep(.history-vxe-pager .vxe-pager--num-btn.is--active) {
  color: #f0f6ff;
  border-color: rgba(111, 154, 211, 0.36);
  background: #2f6fb5;
}

:global(.collector-app.dark) .history-list :deep(.history-vxe-pager .is--disabled) {
  color: rgba(142, 162, 189, 0.42);
  background: rgba(17, 27, 44, 0.42);
}

:global(.collector-app.dark) .task-detail .detail-row,
:global(.collector-app.dark) .trend-item,
:global(.collector-app.dark) .history-log-row {
  border-color: rgba(128, 153, 188, 0.14);
  background: rgba(15, 24, 39, 0.5);
}

:global(.collector-app.dark) .detail-empty {
  color: #8ea2bd;
  background: rgba(15, 24, 39, 0.36);
}

:global(.collector-app.dark) .detail-empty strong,
:global(.collector-app.dark) .task-detail .detail-row strong,
:global(.collector-app.dark) .detail-row .record-content {
  color: #dce7f5;
}

:global(.collector-app.dark) .trend-bar {
  background:
    linear-gradient(180deg, rgba(214, 226, 244, 0.14), transparent 34%),
    linear-gradient(180deg, #4d8ed2, #2f6fb5);
}

:global(.collector-app.dark) .chart-caption,
:global(.collector-app.dark) .trend-item small,
:global(.collector-app.dark) .history-log-row time {
  color: #8ea2bd;
}
</style>
