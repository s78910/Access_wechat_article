export type LogScrollMetrics = {
  scrollHeight: number
  scrollTop: number
  clientHeight: number
}

const DEFAULT_BOTTOM_THRESHOLD_PX = 24
export const LOG_AUTO_FOLLOW_IDLE_MS = 10_000

export function isLogScrollNearBottom(
  metrics: LogScrollMetrics,
  thresholdPx = DEFAULT_BOTTOM_THRESHOLD_PX,
) {
  const remaining = metrics.scrollHeight - metrics.scrollTop - metrics.clientHeight
  return remaining <= thresholdPx
}

export function readLogScrollMetricsFromEvent(event: Event): LogScrollMetrics | null {
  const target = event.currentTarget as Partial<LogScrollMetrics> | null
  if (!target) {
    return null
  }

  const scrollHeight = Number(target.scrollHeight)
  const scrollTop = Number(target.scrollTop)
  const clientHeight = Number(target.clientHeight)
  if (![scrollHeight, scrollTop, clientHeight].every(Number.isFinite)) {
    return null
  }

  return {
    scrollHeight,
    scrollTop,
    clientHeight,
  }
}

export function canResumeLogAutoFollow(
  lastInteractionAt: number,
  now: number,
  idleMs = LOG_AUTO_FOLLOW_IDLE_MS,
) {
  return Math.max(0, now - lastInteractionAt) >= idleMs
}
