import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const currentDir = dirname(fileURLToPath(import.meta.url))
const appVue = readFileSync(resolve(currentDir, '../App.vue'), 'utf8')
const appTopbarVue = readFileSync(resolve(currentDir, '../components/AppTopbar.vue'), 'utf8')
const healthDialogVue = readFileSync(resolve(currentDir, '../components/TopbarHealthDialog.vue'), 'utf8')
const iconRegistrySource = readFileSync(resolve(currentDir, '../icons/fontAwesomeIcons.ts'), 'utf8')

test('顶部中间区域改为四项健康摘要，不再显示旧代理条', () => {
  assert.match(appVue, /const topbarHealthItems = computed\(\(\) => \[/)
  assert.match(appVue, /label:\s*'HTTPS 状态'/)
  assert.match(appVue, /label:\s*'HTTPS 状态'[\s\S]*?icon:\s*'fa-solid fa-lock'/)
  assert.match(appVue, /label:\s*'CA 证书'/)
  assert.match(appVue, /label:\s*'CA 证书'[\s\S]*?icon:\s*'fa-solid fa-shield-halved'/)
  assert.match(appVue, /label:\s*'代理端口'/)
  assert.match(appVue, /icon:\s*'fa-solid fa-network-wired'/)
  assert.match(appVue, /label:\s*'数据目录'/)
  assert.match(appVue, /icon:\s*'fa-solid fa-database'/)
  assert.match(appVue, /<AppTopbar[\s\S]*:health-items="topbarHealthItems"/)

  assert.match(appTopbarVue, /healthItems\?: TopbarHealthItem\[\]/)
  assert.match(appTopbarVue, /class="topbar-health"/)
  assert.match(appTopbarVue, /v-for="item in props\.healthItems"/)
  assert.match(appTopbarVue, /\{\{ item\.label \}\}/)
  assert.match(appTopbarVue, /\{\{ item\.value \}\}/)
  assert.doesNotMatch(appTopbarVue, /class="proxy-strip"/)
  assert.doesNotMatch(appTopbarVue, /MITM 代理程序/)
  assert.doesNotMatch(appTopbarVue, /系统代理：/)
})

test('FontAwesome 注册表包含顶部健康摘要所需图标', () => {
  assert.match(iconRegistrySource, /'fa-solid fa-shield-halved':/)
  assert.match(iconRegistrySource, /'fa-solid fa-lock':/)
  assert.match(iconRegistrySource, /'fa-solid fa-sun':/)
  assert.match(iconRegistrySource, /'fa-solid fa-sun':\s*\{[\s\S]*?viewBox:\s*'0 0 640 640'/)
  assert.match(iconRegistrySource, /'fa-solid fa-sun':\s*\{[\s\S]*?M320 32C328\.4 32 336\.3 36\.4/)
  assert.match(iconRegistrySource, /'fa-solid fa-moon':\s*\{[\s\S]*?viewBox:\s*'0 0 640 640'/)
  assert.match(iconRegistrySource, /'fa-solid fa-moon':\s*\{[\s\S]*?M320 64C178\.6 64 64 178\.6/)
  assert.match(iconRegistrySource, /'fa-solid fa-network-wired':/)
  assert.match(iconRegistrySource, /'fa-solid fa-database':/)
  assert.match(iconRegistrySource, /'fa-solid fa-rotate':/)
  assert.match(iconRegistrySource, /'fa-solid fa-circle-check':/)
  assert.match(iconRegistrySource, /'fa-solid fa-triangle-exclamation':/)
})

test('顶部健康状态由统一检测结果驱动，不再从任务摘要推测', () => {
  assert.match(appVue, /type HealthCheckTarget = 'https' \| 'ca' \| 'proxy-port' \| 'storage'/)
  assert.match(appVue, /function buildTopbarCheckingState\([^)]*\): TopbarHealthState[\s\S]*?value:\s*'检测中'[\s\S]*?statusIcon:\s*'fa-solid fa-rotate'[\s\S]*?tone:\s*'warning'/)
  assert.match(appVue, /const topbarHealthStates = ref<Record<HealthCheckTarget, TopbarHealthState>>/)
  assert.match(appVue, /function applyHealthCheckResult\(result: HealthCheckResult\)/)
  assert.match(appVue, /function normalizeTopbarHealthValue\(result: HealthCheckResult\)/)
  assert.match(appVue, /value:\s*normalizeTopbarHealthValue\(result\)/)
  assert.doesNotMatch(appVue, /value:\s*result\.label/)
  assert.match(appVue, /statusIcon:\s*result\.ok[\s\S]*?'fa-solid fa-circle-check'[\s\S]*?'fa-solid fa-triangle-exclamation'/)
  assert.doesNotMatch(appVue, /topbarProxyPortConflict/)
  assert.doesNotMatch(appVue, /topbarStorageHealthy/)
})

test('顶部健康块只显示短状态文字，避免文字超出块范围', () => {
  assert.match(appVue, /if \(result\.ok\) \{\s*return '正常'\s*\}/)
  assert.match(appVue, /return '异常'/)
  assert.match(appVue, /value:\s*'失败'/)
  assert.doesNotMatch(appVue, /value:\s*'检测失败'/)
})

test('启动检测只请求一次并把四项结果同步到顶部', () => {
  assert.match(appVue, /let startupHealthCheckRequested = false/)
  assert.match(appVue, /async function refreshStartupHealthChecks\(\)[\s\S]*?if \(startupHealthCheckRequested\)[\s\S]*?startupHealthCheckRequested = true/)
  assert.match(appVue, /const result = await runStartupHealthChecks\(\)/)
  assert.match(appVue, /HEALTH_CHECK_TARGETS[\s\S]*?applyHealthCheckResult/)
  assert.match(appVue, /onMounted\(async \(\) => \{[\s\S]*?await refreshTaskRuntime\(\)[\s\S]*?await refreshStartupHealthChecks\(\)/)
  assert.equal((appVue.match(/refreshStartupHealthChecks\(\)/g) ?? []).length, 2)
})

test('启动自检先读取版本状态，仅需要时打开弹窗并执行自检', () => {
  assert.match(appVue, /getStartupSelfCheckStatus/)
  assert.match(appVue, /runStartupSelfCheck/)
  assert.match(appVue, /let startupSelfCheckRequested = false/)
  assert.match(appVue, /async function refreshStartupSelfCheck\(\)[\s\S]*?const status = await getStartupSelfCheckStatus\(\)/)
  assert.match(appVue, /if \(!status\.needsSelfCheck\)[\s\S]*?return/)
  assert.match(appVue, /startupSelfCheckDialogVisible\.value = true[\s\S]*?await runStartupSelfCheck\(\)/)
  assert.match(appVue, /onMounted\(async \(\) => \{[\s\S]*?await refreshTaskRuntime\(\)[\s\S]*?await refreshStartupSelfCheck\(\)/)
  assert.match(appVue, /<TopbarHealthDialog[\s\S]*?:visible="startupSelfCheckDialogVisible"[\s\S]*?title="启动自检"/)
  assert.match(appVue, /正在自检/)
})

test('点击状态块立即打开统一弹窗，再执行对应单项检测', () => {
  assert.match(appTopbarVue, /type TopbarHealthKey = 'https' \| 'ca' \| 'proxy-port' \| 'storage'/)
  assert.match(appTopbarVue, /key: TopbarHealthKey/)
  assert.match(appTopbarVue, /healthCheck: \[key: TopbarHealthKey\]/)
  assert.match(appTopbarVue, /<a-button[\s\S]*?v-for="item in props\.healthItems"[\s\S]*?@click="emit\('healthCheck', item\.key\)"/)
  assert.doesNotMatch(appTopbarVue, /<button[\s\S]*?v-for="item in props\.healthItems"/)
  assert.match(appVue, /@health-check="handleTopbarHealthCheck"/)

  const handler = appVue.match(/async function handleTopbarHealthCheck[\s\S]*?\n\}/)?.[0] ?? ''
  assert.ok(handler.indexOf('healthDialogVisible.value = true') >= 0)
  assert.ok(handler.indexOf('healthDialogVisible.value = true') < handler.indexOf('await checkHealthTarget(target)'))
  assert.match(handler, /topbarHealthStates\.value\[target\] = checkingState/)
  assert.match(handler, /applyHealthCheckResult\(result\)/)

  assert.match(appVue, /<TopbarHealthDialog[\s\S]*?:visible="healthDialogVisible"/)
  assert.match(healthDialogVue, /role="dialog"/)
  assert.match(healthDialogVue, /正在检测/)
  assert.match(healthDialogVue, /v-for="item in props\.items"/)
  assert.match(healthDialogVue, /@click="emit\('close'\)"/)
})

test('四项健康状态使用醒目的状态图标替代圆点分隔符', () => {
  assert.match(appTopbarVue, /icon\?: string/)
  assert.match(appTopbarVue, /statusIcon: string/)
  assert.match(appTopbarVue, /<AppIcon v-if="item\.icon"/)
  assert.match(appTopbarVue, /class="health-status-icon"/)
  assert.doesNotMatch(appTopbarVue, /class="health-separator"/)
  assert.doesNotMatch(appTopbarVue, />·<\/span>/)

  assert.match(appVue, /statusIcon:\s*topbarHealthStates\.value\.https\.statusIcon/)
  assert.match(appVue, /statusIcon:\s*topbarHealthStates\.value\.ca\.statusIcon/)
  assert.match(appVue, /statusIcon:\s*topbarHealthStates\.value\['proxy-port'\]\.statusIcon/)
  assert.match(appVue, /statusIcon:\s*topbarHealthStates\.value\.storage\.statusIcon/)
})

test('顶部六个矩形块组成靠右排列的统一工具组', () => {
  assert.match(appTopbarVue, /class="topbar-tools"/)
  assert.match(appTopbarVue, /<a-button[\s\S]*?class="github-pill"[\s\S]*?:href="props\.githubUrl"/)
  assert.match(appTopbarVue, /<a-button[\s\S]*?:class="\['theme-switch',\s*\{ 'is-dark': props\.isDark \}\]"/)
  assert.doesNotMatch(appTopbarVue, /<a\s+[\s\S]*?class="github-pill"/)
  assert.match(appTopbarVue, /theme-switch/)
  assert.match(appTopbarVue, /<span class="sun"><AppIcon icon="fa-solid fa-sun" \/><\/span>/)
  assert.match(appTopbarVue, /aria-label="切换明暗主题"/)
  assert.match(appTopbarVue, /\.topbar\s*\{[\s\S]*?display:\s*grid;[\s\S]*?grid-template-columns:\s*500px minmax\(0, 1fr\);/)
  assert.doesNotMatch(appTopbarVue, /grid-template-columns:\s*500px\s+640px\s+300px/)
  assert.match(appTopbarVue, /\.brand h1\s*\{[\s\S]*?white-space:\s*nowrap;/)
  assert.match(appTopbarVue, /\.topbar-tools\s*\{[\s\S]*?justify-content:\s*flex-end;[\s\S]*?box-sizing:\s*border-box;[\s\S]*?width:\s*100%;[\s\S]*?margin-left:\s*0;[\s\S]*?margin-right:\s*0;[\s\S]*?padding-right:\s*28px;/)
  assert.match(appTopbarVue, /\.topbar-tools\s*\{[\s\S]*?gap:\s*12px;/)
  assert.match(appTopbarVue, /\.topbar-health\s*\{[\s\S]*?display:\s*contents;/)
  assert.doesNotMatch(appTopbarVue, /--health-item-width/)
  assert.match(appTopbarVue, /\.top-actions\s*\{[\s\S]*?display:\s*contents;/)
  assert.match(appTopbarVue, /@media\s*\(max-width:\s*1500px\)[\s\S]*?\.topbar-tools\s*\{[\s\S]*?gap:\s*12px;/)

  assert.match(appTopbarVue, /\.health-item\s*\{[\s\S]*?justify-content:\s*center;[\s\S]*?gap:\s*6px;[\s\S]*?flex:\s*0 0 auto;[\s\S]*?width:\s*auto;[\s\S]*?min-width:\s*max-content;[\s\S]*?height:\s*48px;[\s\S]*?padding:\s*0 12px;[\s\S]*?border-radius:\s*10px;/)
  assert.match(appTopbarVue, /\.github-pill\s*\{[\s\S]*?height:\s*48px;[\s\S]*?width:\s*auto;[\s\S]*?min-width:\s*max-content;[\s\S]*?border-radius:\s*10px;/)
  assert.match(appTopbarVue, /\.github-pill > \.app-icon:first-child\s*\{[\s\S]*?font-size:\s*18px;/)
  assert.match(appTopbarVue, /\.theme-switch\s*\{[\s\S]*?height:\s*48px;[\s\S]*?border-radius:\s*10px;[\s\S]*?cursor:\s*pointer;/)
  assert.match(appTopbarVue, /\.theme-switch span\s*\{[\s\S]*?font-size:\s*20px;/)
  assert.match(appTopbarVue, /\.theme-switch \.sun\s*\{[\s\S]*?color:\s*rgba\(21, 56, 111, 0\.62\);[\s\S]*?background:\s*#b7d8ff;/i)
  assert.match(appTopbarVue, /\.theme-switch \.moon\s*\{[\s\S]*?background:\s*transparent;/i)
  assert.match(appTopbarVue, /\.theme-switch\.is-dark \.sun\s*\{[\s\S]*?background:\s*transparent;/i)
  assert.match(appTopbarVue, /\.theme-switch\.is-dark \.moon\s*\{[\s\S]*?color:\s*#dceaff;[\s\S]*?background:\s*#275d9f;/i)
})

test('顶部健康块不在窄视口媒体查询中二次缩窄', () => {
  assert.doesNotMatch(appTopbarVue, /@media\s*\(max-width:\s*1500px\)[\s\S]*?\.topbar-health\s*\{/)
  assert.doesNotMatch(appTopbarVue, /@media\s*\(max-width:\s*1500px\)[\s\S]*?\.health-item\s*\{/)
})

test('健康块文字和图标使用主题深蓝并提高信息字号', () => {
  assert.match(appTopbarVue, /\.health-label\s*\{[\s\S]*?color:\s*#15386f;[\s\S]*?font-size:\s*15px;[\s\S]*?transform:\s*translateY\(1px\);/i)
  assert.match(appTopbarVue, /\.health-icon\s*\{[\s\S]*?color:\s*#15386f;[\s\S]*?font-size:\s*16px;/i)
  assert.match(appTopbarVue, /\.health-value\s*\{[\s\S]*?min-width:\s*max-content;[\s\S]*?overflow:\s*visible;[\s\S]*?font-size:\s*14px;[\s\S]*?text-overflow:\s*clip;[\s\S]*?transform:\s*translateY\(1px\);/i)
})

test('健康状态右侧使用克制的语义色，并为深色主题提供高对比颜色', () => {
  assert.match(appTopbarVue, /\.health-status-icon\s*\{[\s\S]*?color:\s*var\(--health-state-color\);/)
  assert.match(appTopbarVue, /\.health-value\s*\{[\s\S]*?color:\s*var\(--health-state-color\);/)
  assert.match(appTopbarVue, /\.health-item--success\s*\{[\s\S]*?--health-state-color:\s*#237a57;/i)
  assert.match(appTopbarVue, /\.health-item--warning\s*\{[\s\S]*?--health-state-color:\s*#8a6517;/i)
  assert.match(appTopbarVue, /\.health-item--danger\s*\{[\s\S]*?--health-state-color:\s*#b54745;/i)
  assert.match(appTopbarVue, /:global\(\.collector-app\.dark \.health-item--success\)\s*\{[\s\S]*?--health-state-color:\s*#83c7a8;/i)
  assert.match(appTopbarVue, /:global\(\.collector-app\.dark \.health-item--warning\)\s*\{[\s\S]*?--health-state-color:\s*#d8b45f;/i)
  assert.match(appTopbarVue, /:global\(\.collector-app\.dark \.health-item--danger\)\s*\{[\s\S]*?--health-state-color:\s*#e08d88;/i)
  assert.match(appTopbarVue, /\.health-item--checking \.health-status-icon\s*\{[\s\S]*?animation:\s*health-status-spin 980ms linear infinite;/)
  assert.match(appTopbarVue, /@media \(prefers-reduced-motion: reduce\)[\s\S]*?\.health-item--checking \.health-status-icon\s*\{[\s\S]*?animation:\s*none;/)
  assert.doesNotMatch(appTopbarVue, /:global\(\.dark\)/)
})
