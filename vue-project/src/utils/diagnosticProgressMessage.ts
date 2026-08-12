export type DiagnosticProgressCell = {
  label: string
  value: unknown
}

export type DiagnosticProgressItem = DiagnosticProgressCell & {
  cells?: DiagnosticProgressCell[]
}

type ResolveDiagnosticProgressMessageOptions = {
  status?: string
  action?: string
  tone?: string
  message?: string
  items?: DiagnosticProgressItem[]
}

const IGNORED_LABELS = new Set([
  '流程',
  '状态',
  '动作',
  '失败原因',
  '总耗时',
  '整体耗时',
  '整理耗时',
])

const RUNNING_WORDS = ['执行中', '启动中', '等待', '正在', '处理中', 'running', 'pending']
const DONE_WORDS = ['完成', '已完成', '已保存', '已返回', '已记录', '已解析', '已检测', '已读取', '已提交', '已创建', '已关闭']

export function resolveDiagnosticProgressMessage(options: ResolveDiagnosticProgressMessageOptions): string {
  const items = (options.items ?? []).filter(isProgressStep)
  const runningIndex = items.findIndex(isRunningStep)

  if (runningIndex >= 0) {
    const current = items[runningIndex]!
    const previousCompleted = findPreviousCompleted(items, runningIndex)

    return previousCompleted
      ? `${previousCompleted.label}完成，正在${current.label}`
      : `正在${current.label}`
  }

  const fallbackCurrent = resolveCurrentFromMessage(options.message)
  const latestCompleted = findLatestCompleted(items)
  if (isRunningStatus(options.status, options.tone) && fallbackCurrent) {
    return latestCompleted
      ? `${latestCompleted.label}完成，正在${fallbackCurrent}`
      : `正在${fallbackCurrent}`
  }

  if (isTerminalStatus(options.status, options.tone) && latestCompleted) {
    return `${latestCompleted.label}完成`
  }

  return String(options.message || '')
}

function isProgressStep(item: DiagnosticProgressItem): boolean {
  const label = String(item.label || '').trim()
  if (!label || IGNORED_LABELS.has(label)) {
    return false
  }

  return !label.endsWith('耗时') && !label.includes('失败原因')
}

function isRunningStep(item: DiagnosticProgressItem): boolean {
  const value = normalizeText(item.value)
  if (value.startsWith('已') || DONE_WORDS.some((word) => value.includes(word))) {
    return false
  }

  return RUNNING_WORDS.some((word) => value.toLowerCase().includes(word.toLowerCase()))
}

function isCompletedStep(item: DiagnosticProgressItem): boolean {
  const value = normalizeText(item.value)
  if (/\d+(?:\.\d+)?\s*秒/.test(value)) {
    return true
  }
  if (value.startsWith('已') || DONE_WORDS.some((word) => value.includes(word))) {
    return true
  }

  return (item.cells ?? []).some((cell) => {
    const text = normalizeText(cell.value)
    return text.startsWith('已') || DONE_WORDS.some((word) => text.includes(word))
  })
}

function findPreviousCompleted(items: DiagnosticProgressItem[], beforeIndex: number): DiagnosticProgressItem | null {
  for (let index = beforeIndex - 1; index >= 0; index -= 1) {
    const item = items[index]!
    if (isCompletedStep(item)) {
      return item
    }
  }

  return null
}

function findLatestCompleted(items: DiagnosticProgressItem[]): DiagnosticProgressItem | null {
  return findPreviousCompleted(items, items.length)
}

function isRunningStatus(status?: string, tone?: string): boolean {
  const normalized = normalizeText(status).toLowerCase()
  return normalized === 'running' || tone === 'info'
}

function isTerminalStatus(status?: string, tone?: string): boolean {
  const normalized = normalizeText(status).toLowerCase()
  return ['completed', 'success', 'skipped', 'failed', 'error'].includes(normalized)
    || ['success', 'warning', 'error'].includes(String(tone || ''))
}

function resolveCurrentFromMessage(message?: string): string {
  const text = normalizeText(message)
    .replace(/[。.!！…]+$/g, '')
    .replace(/\.\.\.$/g, '')
  if (!text) {
    return ''
  }

  const runningMatch = text.match(/正在(.+)$/)
  if (runningMatch?.[1]) {
    return runningMatch[1].trim()
  }

  const waitingMatch = text.match(/等待(.+)$/)
  if (waitingMatch?.[1]) {
    return `等待${waitingMatch[1].trim()}`
  }

  return ''
}

function normalizeText(value: unknown): string {
  return String(value ?? '').trim()
}
