type ProxyTone = 'blue' | 'green' | 'red' | 'purple' | 'orange'

export type ProxyDisplayStatus = {
  label: string
  tone: ProxyTone
}

export type ProxyStatusLike = {
  host?: string
  port?: number
  enabled?: boolean
  mitmEnabled?: boolean
  systemProxyEnabled?: boolean
  systemProxyActive?: boolean
  systemProxyReadable?: boolean
  systemProxyServer?: string
  configuredProxyServer?: string
  systemProxyReadError?: string
}

export function resolveProxyConfiguredServer(proxy?: ProxyStatusLike) {
  return String(proxy?.configuredProxyServer || '').trim()
}

export function resolveProxyConnectionLabel(mitmConnected: boolean, proxy?: ProxyStatusLike) {
  if (!mitmConnected) {
    return '未连接'
  }

  const configuredServer = resolveProxyConfiguredServer(proxy)
  return configuredServer ? `已连接 ${configuredServer}` : '已连接'
}

function resolveSystemProxyServer(proxy?: ProxyStatusLike) {
  return String(proxy?.systemProxyServer || '').trim()
}

function hasReadableSystemProxySnapshot(proxy?: ProxyStatusLike) {
  if (!proxy) {
    return false
  }

  if (proxy.systemProxyReadable === false) {
    return false
  }

  return proxy.systemProxyReadable === true
    || typeof proxy.systemProxyActive === 'boolean'
    || typeof proxy.systemProxyEnabled === 'boolean'
    || resolveSystemProxyServer(proxy).length > 0
}

export function resolveProxyDisplayStatus(taskStatus: string, proxy?: ProxyStatusLike): ProxyDisplayStatus {
  const mitmEnabled = Boolean(proxy?.mitmEnabled)
  const configuredServer = resolveProxyConfiguredServer(proxy)
  const systemServer = resolveSystemProxyServer(proxy)
  const hasSystemSnapshot = hasReadableSystemProxySnapshot(proxy)
  const systemProxyActive = Boolean(proxy?.systemProxyActive ?? proxy?.systemProxyEnabled)

  if (!mitmEnabled && hasSystemSnapshot && systemProxyActive) {
    return { label: '系统代理已开启，MITM 未开启', tone: 'red' }
  }

  if (!mitmEnabled) {
    return { label: taskStatus === 'stopped' ? 'MITM 已停止' : 'MITM 未开启', tone: 'orange' }
  }

  if (mitmEnabled && !hasSystemSnapshot) {
    return { label: '系统代理状态未知', tone: 'orange' }
  }

  if (mitmEnabled && systemProxyActive && configuredServer && systemServer === configuredServer) {
    return { label: `已接管 ${systemServer}`, tone: 'green' }
  }

  if (mitmEnabled && systemProxyActive && systemServer && configuredServer && systemServer !== configuredServer) {
    return { label: `代理异常 ${systemServer}`, tone: 'red' }
  }

  if (mitmEnabled && systemProxyActive && systemServer && !configuredServer) {
    return { label: `系统代理已开启 ${systemServer}`, tone: 'orange' }
  }

  if (mitmEnabled && systemProxyActive && !systemServer) {
    return { label: '系统代理状态未知', tone: 'orange' }
  }

  if (mitmEnabled) {
    return { label: configuredServer ? `监听中 ${configuredServer}` : 'MITM 监听中', tone: 'orange' }
  }

  return { label: 'MITM 未开启', tone: 'orange' }
}
