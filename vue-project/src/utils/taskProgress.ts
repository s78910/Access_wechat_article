import type { TaskLogItem } from '../bridge/pythonApi'

export type TaskProgressSummary = {
  completedCount: number
  failedCount: number
  progressPercent: number
  totalLabel: string
}

type ResolveTaskProgressSummaryOptions = {
  plannedCount: number
  logs: Array<TaskLogItem & { progress?: unknown }>
}

const FINAL_SUMMARY_PATTERN = /本次保存\s*(\d+)\s*\/\s*(\d+|全部)\s*篇[，,]\s*失败\s*(\d+)\s*篇/
const SAVED_ARTICLE_PATTERN = /主页第\s*\d+\s*篇文章已保存/
const FAILED_ARTICLE_PATTERN = /主页第\s*\d+\s*篇文章保存失败/

export function resolveTaskProgressSummary(options: ResolveTaskProgressSummaryOptions): TaskProgressSummary {
  const logs = options.logs ?? []
  const plannedCount = normalizePlannedCount(options.plannedCount)
  const totalLabel = plannedCount === 0 ? '全部' : String(plannedCount)
  const finalSummary = readFinalSummary(logs)
  if (finalSummary) {
    const totalFromLog = finalSummary.totalLabel === '全部'
      ? plannedCount
      : Number(finalSummary.totalLabel)
    const total = totalFromLog > 0 ? totalFromLog : finalSummary.completedCount + finalSummary.failedCount

    return {
      completedCount: finalSummary.completedCount,
      failedCount: finalSummary.failedCount,
      totalLabel: finalSummary.totalLabel,
      progressPercent: total > 0 ? 100 : 0,
    }
  }

  const completedCount = countMatchingLogs(logs, SAVED_ARTICLE_PATTERN)
  const failedCount = countMatchingLogs(logs, FAILED_ARTICLE_PATTERN)
  const explicitProgress = readLatestProgress(logs)
  const inferredProgress = plannedCount > 0
    ? Math.min(100, Math.round(((completedCount + failedCount) / plannedCount) * 100))
    : 0

  return {
    completedCount,
    failedCount,
    totalLabel,
    progressPercent: explicitProgress ?? inferredProgress,
  }
}

function normalizePlannedCount(value: number) {
  return Number.isFinite(value) ? Math.max(0, Math.floor(value)) : 1
}

function readFinalSummary(logs: TaskLogItem[]) {
  for (let index = logs.length - 1; index >= 0; index -= 1) {
    const match = String(logs[index]?.message ?? '').match(FINAL_SUMMARY_PATTERN)
    if (match) {
      return {
        completedCount: Number(match[1] ?? 0),
        totalLabel: match[2] ?? '全部',
        failedCount: Number(match[3] ?? 0),
      }
    }
  }

  return null
}

function readLatestProgress(logs: Array<TaskLogItem & { progress?: unknown }>) {
  for (let index = logs.length - 1; index >= 0; index -= 1) {
    const progress = Number(logs[index]?.progress)
    if (Number.isFinite(progress)) {
      return Math.min(100, Math.max(0, Math.round(progress)))
    }
  }

  return null
}

function countMatchingLogs(logs: TaskLogItem[], pattern: RegExp) {
  return logs.filter((item) => pattern.test(String(item.message ?? ''))).length
}
