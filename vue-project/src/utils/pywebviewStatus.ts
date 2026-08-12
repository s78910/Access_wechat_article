type PywebviewEnvironment = {
  appVersion?: string
  systemLabel?: string
  pythonVersion?: string
  mitmproxyVersion?: string
  playwrightVersion?: string
  pywebviewVersion?: string
}

type PywebviewStatusPayload = {
  ok: boolean
  status: string
  environment?: PywebviewEnvironment
}

export type EnvironmentStatus = {
  systemLabel: string
  appVersion: string
  pythonVersion: string
  mitmproxyVersion: string
  playwrightVersion: string
  pywebviewVersion: string
}

export type ResolvedPywebviewEnvironmentStatus = {
  shouldRetry: boolean
  pywebviewStatusLabel: string
  environmentStatus: EnvironmentStatus
}

export const INITIAL_ENVIRONMENT_STATUS: EnvironmentStatus = {
  systemLabel: '检测中',
  appVersion: '检测中',
  pythonVersion: '检测中',
  mitmproxyVersion: '检测中',
  playwrightVersion: '检测中',
  pywebviewVersion: '检测中',
}

function buildEnvironmentStatus(
  source: PywebviewEnvironment | undefined,
  fallbackLabel: string,
): EnvironmentStatus {
  return {
    systemLabel: source?.systemLabel || '未知系统',
    appVersion: source?.appVersion || '未设置',
    pythonVersion: source?.pythonVersion || '未知版本',
    mitmproxyVersion: source?.mitmproxyVersion || '未知版本',
    playwrightVersion: source?.playwrightVersion || '未知版本',
    pywebviewVersion: source?.pywebviewVersion || fallbackLabel,
  }
}

export function resolvePywebviewEnvironmentStatus(
  status: PywebviewStatusPayload,
): ResolvedPywebviewEnvironmentStatus {
  if (status.status === 'browser-preview') {
    return {
      shouldRetry: true,
      pywebviewStatusLabel: '检测中',
      environmentStatus: { ...INITIAL_ENVIRONMENT_STATUS },
    }
  }

  const pywebviewStatusLabel = status.ok ? '已连接' : '浏览器预览'
  return {
    shouldRetry: false,
    pywebviewStatusLabel,
    environmentStatus: buildEnvironmentStatus(status.environment, pywebviewStatusLabel),
  }
}

export function getBrowserPreviewEnvironmentStatus(): ResolvedPywebviewEnvironmentStatus {
  const pywebviewStatusLabel = '浏览器预览'
  return {
    shouldRetry: false,
    pywebviewStatusLabel,
    environmentStatus: buildEnvironmentStatus(undefined, pywebviewStatusLabel),
  }
}

export function getEnvironmentErrorStatus(): ResolvedPywebviewEnvironmentStatus {
  return {
    shouldRetry: false,
    pywebviewStatusLabel: '连接失败',
    environmentStatus: {
      systemLabel: '读取失败',
      appVersion: '读取失败',
      pythonVersion: '读取失败',
      mitmproxyVersion: '读取失败',
      playwrightVersion: '读取失败',
      pywebviewVersion: '读取失败',
    },
  }
}
