import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const currentDir = dirname(fileURLToPath(import.meta.url))
const settingsPageSource = readFileSync(resolve(currentDir, '../pages/SettingsPage.vue'), 'utf8')
const iconRegistrySource = readFileSync(resolve(currentDir, '../icons/fontAwesomeIcons.ts'), 'utf8')
const pythonApiSource = readFileSync(resolve(currentDir, '../bridge/pythonApi.ts'), 'utf8')
const customYamlSource = readFileSync(resolve(currentDir, '../../../data/custom.yaml'), 'utf8')

function collectYamlLeafKeys(source: string) {
  const stack: Array<{ indent: number, key: string }> = []
  const keys: string[] = []

  for (const rawLine of source.split(/\r?\n/)) {
    const line = rawLine.replace(/\s+#.*$/, '')

    if (!line.trim() || line.trim().startsWith('#')) {
      continue
    }

    const match = line.match(/^(\s*)([A-Za-z0-9_]+):(?:\s*(.*))?$/)

    if (!match) {
      continue
    }

    const indent = match[1].length
    const key = match[2]
    const value = match[3] ?? ''

    while (stack.length && stack[stack.length - 1].indent >= indent) {
      stack.pop()
    }

    const path = [...stack.map((item) => item.key), key]

    if (value.trim() === '') {
      stack.push({ indent, key })
    } else {
      keys.push(path.join('.'))
    }
  }

  return new Set(keys)
}

function extractSettingsCaseBlock(caseName: string) {
  const block = settingsPageSource.match(new RegExp("case '" + caseName + "':[\\s\\S]*?(?=\\n    case '|\\n  \\})"))

  assert.ok(block, `${caseName} 设置块应存在`)

  return block[0]
}

test('系统配置页使用三段式配置中心，不再保留旧基础设置和代理工具面板', () => {
  assert.match(settingsPageSource, /class="settings-three-pane"/)
  assert.match(settingsPageSource, /class="settings-primary-nav"/)
  assert.match(settingsPageSource, /class="settings-secondary-nav"/)
  assert.match(settingsPageSource, /class="settings-detail-pane"/)
  assert.doesNotMatch(settingsPageSource, /class="base-settings page-panel"/)
  assert.doesNotMatch(settingsPageSource, /class="proxy-settings page-panel"/)
})

test('系统配置页使用上下分区，底部固定展示运行环境和快速操作', () => {
  assert.match(settingsPageSource, /class="settings-bottom-panels"/)
  assert.match(settingsPageSource, /class="env-panel page-panel"/)
  assert.match(settingsPageSource, /class="config-actions page-panel"/)
  assert.match(settingsPageSource, />\s*运行环境\s*</)
  assert.match(settingsPageSource, />\s*配置操作\s*</)
  assert.match(settingsPageSource, /v-for="item in settingsEnvironmentItems"/)
  assert.match(settingsPageSource, /class="config-action-heading-icon"[\s\S]*?fa-solid fa-desktop/)
  assert.match(settingsPageSource, /class="config-action-heading-icon"[\s\S]*?fa-solid fa-file-shield/)
  assert.match(settingsPageSource, /class="config-action-grid"/)
})

test('系统配置页快速操作不再提供重启代理按钮', () => {
  const quickActionsBlock = settingsPageSource.match(/<section class="config-actions page-panel"[\s\S]*?<\/section>/)
  assert.ok(quickActionsBlock)
  assert.doesNotMatch(quickActionsBlock[0], /handleApplyAndRestartProxy/)
  assert.doesNotMatch(quickActionsBlock[0], /重启代理/)
  assert.doesNotMatch(quickActionsBlock[0], /fa-solid fa-rotate"/)
  assert.doesNotMatch(quickActionsBlock[0], /handleOpenMitmCertificateDialog/)
  assert.doesNotMatch(quickActionsBlock[0], /清除MITM证书/)
})

test('系统配置页静态菜单图标都来自已登记的 FontAwesome 图标', () => {
  const registeredIcons = new Set(
    [...iconRegistrySource.matchAll(/^\s*'([^']+)':/gm)].map((match) => match[1]),
  )
  const pageIcons = [
    ...new Set(
      [...settingsPageSource.matchAll(/['"]((?:fa-(?:solid|regular|brands) fa-[a-z0-9-]+))['"]/g)].map(
        (match) => match[1],
      ),
    ),
  ]

  assert.ok(pageIcons.length > 0)
  for (const iconName of pageIcons) {
    assert.ok(registeredIcons.has(iconName), `${iconName} 应先登记到 fontAwesomeIcons.ts，避免页面出现空白图标`)
  }
})

test('系统配置页三段式图标使用更轻量的小尺寸', () => {
  assert.match(settingsPageSource, /grid-template-columns:\s*28px minmax\(0, 1fr\)/)
  assert.match(
    settingsPageSource,
    /\.settings-primary-icon,[\s\S]*?\.settings-secondary-icon \{[\s\S]*?width:\s*24px;[\s\S]*?height:\s*24px;[\s\S]*?font-size:\s*12px;/,
  )
  assert.match(
    settingsPageSource,
    /\.settings-detail-icon \{[\s\S]*?width:\s*32px;[\s\S]*?height:\s*32px;[\s\S]*?font-size:\s*14px;/,
  )
  assert.match(
    settingsPageSource,
    /\.settings-detail-icon \{[\s\S]*?color:\s*#15386F;[\s\S]*?background:\s*rgba\(21, 56, 111, 0\.1\);/,
  )
})

test('系统配置页菜单选项、图标和文本统一使用深蓝色', () => {
  assert.match(settingsPageSource, /--settings-brand:\s*#0072EF;/)
  assert.match(settingsPageSource, /--settings-menu-ink:\s*#15386F;/)
  assert.match(settingsPageSource, /--settings-menu-active-ink:\s*#15386F;/)
  assert.match(settingsPageSource, /--settings-menu-active-bg:\s*rgba\(21, 56, 111, 0\.1\);/)
  assert.match(settingsPageSource, /--settings-menu-hover-bg:\s*rgba\(21, 56, 111, 0\.06\);/)
  assert.match(settingsPageSource, /--settings-menu-active-border:\s*rgba\(21, 56, 111, 0\.28\);/)
  assert.match(
    settingsPageSource,
    /\.settings-primary-item,[\s\S]*?\.settings-secondary-item \{[\s\S]*?color:\s*var\(--settings-menu-ink\);/,
  )
  assert.match(
    settingsPageSource,
    /\.settings-primary-icon,[\s\S]*?\.settings-secondary-icon \{[\s\S]*?color:\s*var\(--settings-menu-ink\);/,
  )
  assert.match(
    settingsPageSource,
    /\.settings-primary-item\.active,[\s\S]*?\.settings-secondary-item\.active \{[\s\S]*?background:\s*var\(--settings-menu-active-bg\);/,
  )
  const activeMenuBlock = settingsPageSource.match(
    /\.settings-primary-item\.active,[\s\S]*?\.settings-secondary-item\.active \{[\s\S]*?\n\}/,
  )
  assert.ok(activeMenuBlock)
  assert.doesNotMatch(activeMenuBlock[0], /#2F6F66|74, 174, 159/)
})

test('系统配置页关键文本降低字重，避免中文标题和说明挤成一团', () => {
  assert.match(settingsPageSource, /\.settings-nav-header strong \{[\s\S]*?font-weight:\s*600;/)
  assert.match(settingsPageSource, /\.settings-nav-header span \{[\s\S]*?font-weight:\s*500;/)
  assert.match(settingsPageSource, /\.settings-primary-item strong,[\s\S]*?\.settings-secondary-item strong \{[\s\S]*?font-weight:\s*600;/)
  assert.match(settingsPageSource, /\.settings-detail-header h2 \{[\s\S]*?font-weight:\s*700;/)
  assert.match(settingsPageSource, /\.settings-detail-header small \{[\s\S]*?font-weight:\s*500;/)
  assert.match(settingsPageSource, /\.settings-config-copy strong \{[\s\S]*?font-weight:\s*600;/)
  assert.match(settingsPageSource, /\.settings-config-copy small \{[\s\S]*?font-weight:\s*500;/)
  assert.match(settingsPageSource, /\.settings-config-keyline \{[\s\S]*?font-weight:\s*600;/)
  assert.match(settingsPageSource, /\.settings-page :deep\(\.settings-ant-number \.ant-input-number-input\) \{[\s\S]*?font-weight:\s*600;/)
  assert.match(settingsPageSource, /\.settings-ant-button \{[\s\S]*?font-weight:\s*600;/)
  assert.match(settingsPageSource, /\.config-action-grid :deep\(\.config-action-button\) \{[\s\S]*?font-weight:\s*600;/)
})

test('系统配置页表单控件统一迁移到 Ant Design Vue，不再保留 VXE 和手写数字步进器', () => {
  assert.match(settingsPageSource, /<ASelect\b[\s\S]*?class="settings-ant-control"/)
  assert.match(settingsPageSource, /<AInput\b[\s\S]*?class="settings-ant-control"/)
  assert.match(settingsPageSource, /<ASwitch\b[\s\S]*?class="settings-ant-switch"/)
  assert.match(settingsPageSource, /<AInputNumber\b[\s\S]*?class="settings-ant-number[^"]*"/)
  assert.match(settingsPageSource, /<ACheckbox\b[\s\S]*?class="article-detail-skip-option"/)
  assert.match(settingsPageSource, /function handleWindowDiagnosticScrollStepsNumberChange/)
  assert.match(settingsPageSource, /\.settings-page :deep\(\.settings-ant-control\.ant-select \.ant-select-selector\)/)
  assert.match(settingsPageSource, /\.settings-page :deep\(\.settings-ant-number\.ant-input-number\)/)
  assert.match(settingsPageSource, /\.settings-page :deep\(\.article-detail-skip-option\.ant-checkbox-wrapper\)/)
  assert.match(settingsPageSource, /\.settings-page :deep\(\.settings-ant-switch\.ant-switch-checked\)/)

  assert.doesNotMatch(settingsPageSource, /<Vxe(?:Select|Input|Switch|DatePicker|DateRangePicker)\b/)
  assert.doesNotMatch(settingsPageSource, /settings-vxe-control|settings-vxe-switch|settings-number-stepper/)
})

test('快速操作按钮使用 2x2 居中文本布局并清除默认错位间距', () => {
  assert.match(
    settingsPageSource,
    /\.config-action-grid \{[\s\S]*?grid-template-columns:\s*repeat\(2, minmax\(0, 1fr\)\);[\s\S]*?justify-items:\s*stretch;[\s\S]*?min-height:\s*132px;/,
  )
  assert.match(
    settingsPageSource,
    /\.config-action-grid :deep\(\.config-action-button\) \{[\s\S]*?justify-content:\s*center;[\s\S]*?text-align:\s*center;/,
  )
  assert.match(settingsPageSource, /class="config-action-inline-icon"/)
  assert.match(settingsPageSource, /class="config-action-heading-icon"[\s\S]*?fa-solid fa-file-shield/)
  assert.match(
    settingsPageSource,
    /\.settings-panel-header \.config-action-heading-icon \{[\s\S]*?display:\s*inline-flex;[\s\S]*?margin-top:\s*0;[\s\S]*?overflow:\s*visible;/,
  )
  assert.match(
    settingsPageSource,
    /\.settings-panel-header \.config-action-heading-icon \.app-icon \{[\s\S]*?width:\s*18px;[\s\S]*?height:\s*18px;/,
  )
  assert.match(
    settingsPageSource,
    /\.settings-panel-header \.config-action-heading-copy \{[\s\S]*?display:\s*inline-flex;[\s\S]*?margin-top:\s*0;/,
  )
  assert.match(settingsPageSource, /\.config-action-grid \{[\s\S]*?grid-auto-rows:\s*minmax\(56px, 1fr\);/)
  assert.match(settingsPageSource, /\.config-action-grid :deep\(\.config-action-button\) \{[\s\S]*?min-height:\s*56px;/)
  const configActionBlock = settingsPageSource.match(/<section class="config-actions page-panel"[\s\S]*?<\/section>/)?.[0] ?? ''
  assert.equal((configActionBlock.match(/<AButton[\s\S]*?class="settings-ant-button config-action-button/g) ?? []).length, 4)
  assert.doesNotMatch(configActionBlock, /测试代理连接|handleTestProxyConnection/)
  assert.match(
    settingsPageSource,
    /\.config-action-grid :deep\(\.config-action-button \.ant-btn-icon\+span\),[\s\S]*?\.config-action-grid :deep\(\.config-action-button span\+\.ant-btn-icon\) \{[\s\S]*?margin-inline-start:\s*9px;/,
  )
  assert.match(
    settingsPageSource,
    /\.config-action-inline-icon \{[\s\S]*?font-size:\s*18px;/,
  )
  assert.doesNotMatch(settingsPageSource, /class="config-action-icon"/)
  assert.doesNotMatch(settingsPageSource, /class="config-action-copy"/)
  assert.match(settingsPageSource, /\.config-action-button\.success \{[\s\S]*?--config-action-bg:\s*#35B889;/)
  assert.match(settingsPageSource, /\.config-action-button\.primary \{[\s\S]*?--config-action-bg:\s*#357FD9;/)
  assert.match(settingsPageSource, /\.config-action-button\.orange \{[\s\S]*?--config-action-bg:\s*#F28B3C;/)
  assert.match(settingsPageSource, /\.config-action-button\.ghost \{[\s\S]*?--config-action-color:\s*#357FD9;[\s\S]*?--config-action-bg:\s*#F6FBFF;/)
  assert.doesNotMatch(
    settingsPageSource.match(/<section class="config-actions page-panel"[\s\S]*?<\/section>/)?.[0] ?? '',
    /config-action-button danger|清除MITM证书/,
  )
  assert.doesNotMatch(settingsPageSource, />\s*写入当前系统配置\s*</)
  assert.doesNotMatch(settingsPageSource, />\s*检测代理连通性\s*</)
  assert.match(settingsPageSource, /保存配置/)
  assert.match(settingsPageSource, /恢复默认/)
  assert.doesNotMatch(
    settingsPageSource.match(/<section class="config-actions page-panel"[\s\S]*?<\/section>/)?.[0] ?? '',
    /测试代理/,
  )
  assert.match(settingsPageSource, /清理缓存/)
  assert.match(settingsPageSource, /重新自检/)
})

test('系统配置页重新自检按钮通过启动自检 API 打开结果弹窗', () => {
  assert.match(pythonApiSource, /runStartupSelfCheck/)
  assert.match(settingsPageSource, /runStartupSelfCheck/)
  assert.match(settingsPageSource, /const isRunningStartupSelfCheck = ref\(false\)/)
  assert.match(settingsPageSource, /async function handleRunStartupSelfCheck\(\)[\s\S]*?openDiagnosticResultDialog\([\s\S]*?title:\s*'启动自检'/)
  assert.match(settingsPageSource, /const result = await runStartupSelfCheck\(\)/)
  assert.match(settingsPageSource, /handleRunStartupSelfCheck/)
})

test('设置导航选项只保留名称，不展示解释性副文案和装饰图', () => {
  assert.match(settingsPageSource, /aria-label="设置类别"/)
  assert.match(settingsPageSource, />\s*设置类别\s*</)
  assert.doesNotMatch(settingsPageSource, />\s*一级设置\s*</)
  assert.doesNotMatch(settingsPageSource, /<small>\{\{ category\.summary \}\}<\/small>/)
  assert.doesNotMatch(settingsPageSource, /<small>\{\{ item\.summary \}\}<\/small>/)
  assert.doesNotMatch(settingsPageSource, /panel-corner-art settings-art/)
})

test('系统配置页不再展示顶部运行状态指标块', () => {
  assert.doesNotMatch(settingsPageSource, /data-impeccable-variants/)
  assert.doesNotMatch(settingsPageSource, /settingsMetrics/)
  assert.doesNotMatch(settingsPageSource, /class="metric-grid settings-metrics/)
  assert.doesNotMatch(settingsPageSource, /grid-area:\s*metrics/)
})

test('设置详情区在未选择具体二级项时展示当前一级分类说明', () => {
  assert.match(settingsPageSource, /selectedSettingsItem/)
  assert.match(settingsPageSource, /settings-category-overview/)
  assert.match(settingsPageSource, /请选择左侧具体设置项/)
  assert.match(settingsPageSource, /当前分类包含/)
  assert.match(settingsPageSource, /<div v-if="selectedSettingsItem" class="settings-detail-title-row">/)
  assert.match(settingsPageSource, /<span class="settings-detail-icon">/)
  assert.match(settingsPageSource, /<h3>设置说明<\/h3>/)
  assert.doesNotMatch(settingsPageSource, /selectedSettingsItem\?\.icon \?\? selectedSettingsCategory\.icon/)
  assert.doesNotMatch(settingsPageSource, /<p v-if="selectedSettingsItem">具体设置<\/p>/)
  assert.match(settingsPageSource, /class="settings-detail-title-row"/)
  assert.match(settingsPageSource, /<h2>\{\{ selectedSettingsItem\.label \}\}<\/h2>/)
  assert.doesNotMatch(settingsPageSource, /<p>\{\{ selectedSettingsCategory\.label \}\}<\/p>/)
  assert.doesNotMatch(settingsPageSource, /\{\{ selectedSettingsCategory\.label \}\}说明/)
})

test('设置详情区使用一行一块的配置表单样式', () => {
  assert.match(settingsPageSource, /class="settings-config-list"/)
  assert.match(settingsPageSource, /settings-config-row/)
  assert.match(settingsPageSource, /class="settings-config-copy"/)
  assert.match(settingsPageSource, /class="settings-config-keyline"/)
  assert.match(settingsPageSource, /settings-config-control/)
  assert.match(settingsPageSource, /class="settings-inline-input"/)
  assert.match(settingsPageSource, /class="settings-ant-button settings-row-button ghost"/)
  assert.match(settingsPageSource, /browseLabel: '浏览'/)
  assert.match(
    settingsPageSource,
    /\.settings-config-list \{[\s\S]*?grid-template-columns:\s*minmax\(0, 1fr\);/,
  )
  assert.match(
    settingsPageSource,
    /\.diagnostic-action-grid \{[\s\S]*?grid-template-columns:\s*minmax\(0, 1fr\);/,
  )
})

test('窗口区间设置使用只读起止输入框并在说明中展示使用区间', () => {
  assert.match(settingsPageSource, /inputType\?: 'text' \| 'number' \| 'number-stepper' \| 'switch' \| 'readonly-range'/)
  assert.match(settingsPageSource, /type SettingsDetailRangeValue/)
  assert.match(settingsPageSource, /class="settings-range-readonly"/)
  assert.match(settingsPageSource, /readonly/)
  assert.match(settingsPageSource, /article_title_poll_interval_seconds_range/)
  assert.match(settingsPageSource, /scroll_probe_interval_seconds_range/)
  assert.match(settingsPageSource, /date_seek_scroll_steps_range/)
  assert.match(settingsPageSource, /使用区间/)
  assert.match(settingsPageSource, /0\.05 秒 ~ 0\.15 秒/)
  assert.match(settingsPageSource, /0\.1 秒 ~ 0\.4 秒/)
  assert.match(settingsPageSource, /3 步 ~ 18 步/)
})

test('已选择二级设置时不再渲染顶部说明提示块', () => {
  assert.doesNotMatch(settingsPageSource, /<p class="detail-note">\{\{ selectedSettingsDetail\.note \}\}<\/p>/)
})

test('诊断工具按钮使用统一宽度、低高度圆角和主题配色', () => {
  assert.match(
    settingsPageSource,
    /\.diagnostic-action-grid :deep\(\.diagnostic-action-button\) \{[\s\S]*?width:\s*168px;[\s\S]*?min-width:\s*168px;[\s\S]*?min-height:\s*52px;[\s\S]*?padding:\s*7px 12px !important;[\s\S]*?border-radius:\s*12px;/,
  )
  assert.match(
    settingsPageSource,
    /\.diagnostic-action-grid :deep\(\.diagnostic-action-button \.ant-btn-icon\) \{[\s\S]*?width:\s*22px;[\s\S]*?margin-inline-end:\s*8px;/,
  )
  assert.match(
    settingsPageSource,
    /\.diagnostic-action-icon \{[\s\S]*?width:\s*22px;[\s\S]*?height:\s*22px;[\s\S]*?border-radius:\s*8px;[\s\S]*?font-size:\s*12px;/,
  )
  assert.match(
    settingsPageSource,
    /\.diagnostic-action-grid :deep\(\.diagnostic-action-button\) \{[\s\S]*?--diagnostic-action-color:\s*#2F6F66;[\s\S]*?--diagnostic-action-bg:\s*#F4FBFA;/,
  )
  assert.match(
    settingsPageSource,
    /\.diagnostic-action-grid :deep\(\.diagnostic-action-button:hover\) \{[\s\S]*?color:\s*var\(--diagnostic-action-hover-color\);[\s\S]*?border-color:\s*var\(--diagnostic-action-hover-border\);[\s\S]*?background:\s*var\(--diagnostic-action-hover-bg\);[\s\S]*?box-shadow:\s*none;[\s\S]*?transform:\s*none;/,
  )
  assert.match(
    settingsPageSource,
    /\.diagnostic-action-grid :deep\(\.diagnostic-action-button\.success\) \{[\s\S]*?--diagnostic-action-bg:\s*#35B889;[\s\S]*?background:\s*#35B889;/,
  )
  assert.match(
    settingsPageSource,
    /\.diagnostic-action-grid :deep\(\.diagnostic-action-button\.orange\) \{[\s\S]*?color:\s*#946012;[\s\S]*?background:\s*#FFF8EA;/,
  )
  assert.match(
    settingsPageSource,
    /\.diagnostic-action-grid :deep\(\.diagnostic-action-button\.primary\) \{[\s\S]*?--diagnostic-action-bg:\s*#357FD9;[\s\S]*?background:\s*#357FD9;/,
  )
  assert.match(
    settingsPageSource,
    /\.diagnostic-action-grid :deep\(\.diagnostic-action-button\.blue\) \{[\s\S]*?--diagnostic-action-bg:\s*#EEF6FF;[\s\S]*?background:\s*#EEF6FF;/,
  )
  assert.match(
    settingsPageSource,
    /\.diagnostic-action-grid :deep\(\.diagnostic-action-button\.teal\) \{[\s\S]*?--diagnostic-action-color:\s*#0F766E;[\s\S]*?background:\s*#ECFDFB;/,
  )
  assert.match(
    settingsPageSource,
    /\.diagnostic-action-grid :deep\(\.diagnostic-action-button\.purple\) \{[\s\S]*?--diagnostic-action-bg:\s*#F5F0FF;[\s\S]*?background:\s*#F5F0FF;/,
  )
  assert.match(
    settingsPageSource,
    /\.diagnostic-action-grid :deep\(\.diagnostic-action-button\.danger\) \{[\s\S]*?color:\s*#B4232E;[\s\S]*?background:\s*#FFF1F1;/,
  )
})

test('diagnostic action rows use semantic tones for window and mitm actions', () => {
  const mitmDiagnosticsBlock = extractSettingsCaseBlock('mitm-diagnostics')
  const windowDiagnosticsBlock = extractSettingsCaseBlock('window-diagnostics')

  assert.match(mitmDiagnosticsBlock, /icon: 'fa-solid fa-certificate', tone: 'primary'/)
  assert.match(settingsPageSource, /const mitmProxyDiagnosticTone = computed<'teal' \| 'orange' \| 'danger'>/)
  assert.match(settingsPageSource, /isMitmProxyPortUnavailable\.value \? 'danger' : isMitmProxyDiagnosticActive\.value \? 'orange' : 'teal'/)
  assert.match(windowDiagnosticsBlock, /icon: 'fa-solid fa-xmark', tone: 'danger'/)
})

test('diagnostic action rows use separated card accents', () => {
  assert.match(settingsPageSource, /'diagnostic-action-row'/)
  assert.match(settingsPageSource, /action\.tone \?\? 'ghost'/)
  assert.match(
    settingsPageSource,
    /\.diagnostic-action-grid\.settings-config-list \{[\s\S]*?gap:\s*12px;/,
  )
  assert.match(
    settingsPageSource,
    /\.diagnostic-action-grid \.settings-config-row \{[\s\S]*?position:\s*relative;[\s\S]*?padding:\s*14px 14px 14px 20px;[\s\S]*?border-color:\s*rgba\(104, 141, 181, 0\.24\);[\s\S]*?box-shadow:\s*0 4px 10px rgba\(21, 56, 111, 0\.06\),[\s\S]*?inset 0 1px 0 rgba\(255, 255, 255, 0\.74\);/,
  )
  assert.match(
    settingsPageSource,
    /\.diagnostic-action-grid \.settings-config-row::before \{[\s\S]*?width:\s*4px;[\s\S]*?background:\s*var\(--diagnostic-row-accent\);/,
  )
  assert.match(
    settingsPageSource,
    /\.diagnostic-action-grid \.settings-config-row:hover \{[\s\S]*?border-color:\s*rgba\(53, 127, 217, 0\.32\);[\s\S]*?box-shadow:\s*0 6px 14px rgba\(21, 56, 111, 0\.09\),/,
  )
  assert.match(settingsPageSource, /\.diagnostic-action-grid \.settings-config-row\.success \{[\s\S]*?--diagnostic-row-accent:\s*#35B889;/)
  assert.match(settingsPageSource, /\.diagnostic-action-grid \.settings-config-row\.orange \{[\s\S]*?--diagnostic-row-accent:\s*#F28B3C;/)
  assert.match(settingsPageSource, /\.diagnostic-action-grid \.settings-config-row\.teal \{[\s\S]*?--diagnostic-row-accent:\s*#159A91;/)
  assert.match(settingsPageSource, /\.diagnostic-action-grid \.settings-config-row\.purple \{[\s\S]*?--diagnostic-row-accent:\s*#8968CD;/)
  assert.match(settingsPageSource, /\.diagnostic-action-grid \.settings-config-row\.danger \{[\s\S]*?--diagnostic-row-accent:\s*#D74D4D;/)
})

test('MITM 管理将证书动作标明 CA，并分别提供系统代理和 MITM 代理切换动作', () => {
  const mitmDiagnosticsBlock = extractSettingsCaseBlock('mitm-diagnostics')

  assert.match(mitmDiagnosticsBlock, /label: 'CA证书检测'/)
  assert.match(mitmDiagnosticsBlock, /label: 'CA证书安装'/)
  assert.match(mitmDiagnosticsBlock, /label: '清除CA证书'/)
  assert.match(mitmDiagnosticsBlock, /label: systemProxyDiagnosticLabel\.value/)
  assert.match(mitmDiagnosticsBlock, /description: systemProxyDiagnosticDescription\.value/)
  assert.match(mitmDiagnosticsBlock, /detail: systemProxyDiagnosticDetail\.value/)
  assert.match(mitmDiagnosticsBlock, /icon: systemProxyDiagnosticIcon\.value/)
  assert.match(mitmDiagnosticsBlock, /tone: systemProxyDiagnosticTone\.value/)
  assert.match(mitmDiagnosticsBlock, /run: toggleSystemProxyDiagnosticAction/)
  assert.match(mitmDiagnosticsBlock, /label: mitmProxyDiagnosticLabel\.value/)
  assert.match(mitmDiagnosticsBlock, /description: mitmProxyDiagnosticDescription\.value/)
  assert.match(mitmDiagnosticsBlock, /detail: mitmProxyDiagnosticDetail\.value/)
  assert.match(mitmDiagnosticsBlock, /icon: mitmProxyDiagnosticIcon\.value/)
  assert.match(mitmDiagnosticsBlock, /tone: mitmProxyDiagnosticTone\.value/)
  assert.match(mitmDiagnosticsBlock, /disabled: \(\) => isSyncingProxyState\.value \|\| isMitmProxyPortUnavailable\.value/)
  assert.match(mitmDiagnosticsBlock, /run: toggleMitmProxyDiagnosticAction/)
  assert.match(settingsPageSource, /const isSystemProxyDiagnosticActive = computed/)
  assert.match(settingsPageSource, /const systemProxyDiagnosticLabel = computed\(\(\) => \(isSystemProxyDiagnosticActive\.value \? '关闭系统代理' : '开启系统代理'\)\)/)
  assert.match(settingsPageSource, /const systemProxyDiagnosticDetail = computed/)
  assert.match(settingsPageSource, /当前代理：/)
  assert.match(settingsPageSource, /const isMitmProxyDiagnosticActive = computed/)
  assert.match(settingsPageSource, /const isMitmProxyPortUnavailable = computed/)
  assert.match(settingsPageSource, /const mitmProxyDiagnosticLabel = computed/)
  assert.match(settingsPageSource, /代理端口不可用/)
  assert.match(settingsPageSource, /待监听端口：/)
  assert.match(settingsPageSource, /已监听端口：/)
})

test('MITM 管理证书和测试动作会打开统一结果弹窗展示后端返回', () => {
  assert.match(settingsPageSource, /diagnosticResultDialogVisible/)
  assert.match(settingsPageSource, /function openDiagnosticResultDialog/)
  assert.match(settingsPageSource, /diagnosticResultItems/)
  assert.match(settingsPageSource, /class="diagnostic-result-dialog"/)
  assert.match(settingsPageSource, /handleCheckCaCertificate[\s\S]*?openDiagnosticResultDialog/)
  assert.match(settingsPageSource, /confirmInstallCaCertificate[\s\S]*?openDiagnosticResultDialog/)
  assert.match(settingsPageSource, /handleTestProxyConnection[\s\S]*?openDiagnosticResultDialog/)
})

test('MITM 管理 CA 证书弹窗使用不透明纸面并限制标题行溢出', () => {
  assert.match(settingsPageSource, /class="mitm-cert-dialog-copy"/)
  assert.match(
    settingsPageSource,
    /\.mitm-cert-dialog \{[\s\S]*?background:\s*#FBFDFF;[\s\S]*?isolation:\s*isolate;/,
  )
  assert.match(settingsPageSource, /\.mitm-cert-dialog-copy \{[\s\S]*?min-width:\s*0;/)
  assert.match(settingsPageSource, /\.mitm-cert-dialog p \{[\s\S]*?overflow-wrap:\s*anywhere;/)
  assert.match(
    settingsPageSource,
    /\.mitm-cert-source-heading \{[\s\S]*?grid-template-columns:\s*36px minmax\(0, 1fr\) max-content;/,
  )
  assert.match(settingsPageSource, /\.mitm-cert-badge \{[\s\S]*?justify-self:\s*end;[\s\S]*?max-width:\s*100%;/)
})

test('MITM 管理 CA 证书弹窗底部取消和知道了按钮有明确可见配色', () => {
  assert.match(
    settingsPageSource,
    /\.mitm-cert-dialog-actions :deep\(\.ant-btn\.config-action-button\.ghost\) \{[\s\S]*?color:\s*#15386F;[\s\S]*?border-color:\s*rgba\(53, 127, 217, 0\.32\);[\s\S]*?background:\s*#EAF4FF;/,
  )
  assert.match(
    settingsPageSource,
    /\.mitm-cert-dialog-actions :deep\(\.ant-btn\.config-action-button\.ghost:not\(:disabled\):hover\) \{[\s\S]*?color:\s*#0F2F61;[\s\S]*?border-color:\s*rgba\(53, 127, 217, 0\.48\);[\s\S]*?background:\s*#DDEEFF;/,
  )
})

test('系统配置诊断结果弹窗使用清晰的状态色和可见操作按钮', () => {
  assert.match(
    settingsPageSource,
    /\.diagnostic-result-dialog \{[\s\S]*?border:\s*1px solid rgba\(89, 130, 181, 0\.34\);[\s\S]*?background:\s*#F8FBFF;/,
  )
  assert.match(
    settingsPageSource,
    /\.diagnostic-result-dialog-icon \{[\s\S]*?color:\s*#15386F;[\s\S]*?background:\s*#E8F2FF;/,
  )
  assert.match(
    settingsPageSource,
    /\.diagnostic-result-dialog h3 \{[\s\S]*?color:\s*#1F3148;/,
  )
  assert.match(
    settingsPageSource,
    /\.diagnostic-result-dialog p \{[\s\S]*?color:\s*#52657B;/,
  )
  assert.match(
    settingsPageSource,
    /\.diagnostic-result-item \{[\s\S]*?border:\s*1px solid #C9D9EB;[\s\S]*?background:\s*#F1F6FC;/,
  )
  assert.match(
    settingsPageSource,
    /\.diagnostic-result-item dt \{[\s\S]*?color:\s*#52657B;/,
  )
  assert.match(
    settingsPageSource,
    /\.diagnostic-result-item dd \{[\s\S]*?color:\s*#24364B;/,
  )
  assert.match(
    settingsPageSource,
    /\.diagnostic-result-dialog :deep\(\.ant-btn\.config-action-button\.primary\) \{[\s\S]*?--config-action-bg:\s*#357FD9;[\s\S]*?--config-action-hover-bg:\s*#2267B8;/,
  )
  assert.match(
    settingsPageSource,
    /:global\(\.collector-app\.dark\) \.diagnostic-result-dialog \{[\s\S]*?border-color:\s*rgba\(111, 154, 211, 0\.34\);[\s\S]*?background:\s*#16243A;/,
  )
  assert.match(
    settingsPageSource,
    /:global\(\.collector-app\.dark\) \.diagnostic-result-item \{[\s\S]*?border-color:\s*rgba\(126, 161, 205, 0\.22\);[\s\S]*?background:\s*#1C2A40;/,
  )
})

test('系统配置诊断结果弹窗使用轻量阴影保持卡片层次', () => {
  assert.match(
    settingsPageSource,
    /\.diagnostic-result-dialog \{[\s\S]*?box-shadow:\s*0 6px 8px rgba\(22, 45, 73, 0\.18\);/,
  )
  assert.match(
    settingsPageSource,
    /:global\(\.collector-app\.dark\) \.diagnostic-result-dialog \{[\s\S]*?box-shadow:\s*0 6px 8px rgba\(0, 0, 0, 0\.28\);/,
  )
})

test('MITM 管理 HTTPS 校验结果弹窗支持四列结果行并隐藏读取字节', () => {
  const checkBlock = settingsPageSource.match(/async function handleTestProxyConnection\(\)[\s\S]*?\n\}/)

  assert.ok(checkBlock)
  assert.match(settingsPageSource, /type DiagnosticResultCell = \{[\s\S]*?label: string[\s\S]*?value: string[\s\S]*?\}/)
  assert.match(settingsPageSource, /cells\?: DiagnosticResultCell\[\]/)
  assert.match(settingsPageSource, /function getDiagnosticResultCells/)
  assert.match(settingsPageSource, /v-for="cell in getDiagnosticResultCells\(item\)"/)
  assert.match(settingsPageSource, /diagnostic-result-item--split/)
  assert.match(
    settingsPageSource,
    /\.diagnostic-result-item\.diagnostic-result-item--split \{[\s\S]*?grid-template-columns:\s*116px minmax\(0, 1fr\) 92px minmax\(0, 0\.75fr\);/,
  )
  assert.match(
    checkBlock[0],
    /label: 'MITM 代理'[\s\S]*?label: '代理地址'[\s\S]*?formatDiagnosticValue\(result\.proxy\)/,
  )
  assert.match(
    checkBlock[0],
    /label: '验证地址'[\s\S]*?formatDiagnosticValue\(result\.url\)[\s\S]*?label: 'HTTP 状态'[\s\S]*?formatDiagnosticValue\(result\.statusCode\)/,
  )
  assert.doesNotMatch(checkBlock[0], /bytesRead|读取字节/)
})

test('系统代理诊断动作不弹结果窗，只通知并刷新真实代理状态', () => {
  const toggleBlock = settingsPageSource.match(/async function toggleSystemProxyDiagnosticAction\(\)[\s\S]*?\n\}/)

  assert.ok(toggleBlock)
  assert.match(toggleBlock[0], /await enableSystemProxy\(\)|await disableSystemProxy\(\)/)
  assert.match(toggleBlock[0], /showConfigNotice/)
  assert.match(toggleBlock[0], /await syncProxySwitchState\(\)/)
  assert.doesNotMatch(toggleBlock[0], /openDiagnosticResultDialog\(/)
})

test('MITM 代理诊断动作不弹结果窗，只通知并刷新端口和监听状态', () => {
  const toggleBlock = settingsPageSource.match(/async function toggleMitmProxyDiagnosticAction\(\)[\s\S]*?\n\}/)

  assert.ok(toggleBlock)
  assert.match(toggleBlock[0], /await startMitmProxy\(\)|await stopMitmProxy\(\)/)
  assert.match(toggleBlock[0], /showConfigNotice/)
  assert.match(toggleBlock[0], /await syncProxySwitchState\(\)/)
  assert.doesNotMatch(toggleBlock[0], /openDiagnosticResultDialog\(/)
})

test('HTTPS 校验动作立即弹窗并按代理生命周期顺序执行', () => {
  const checkBlock = settingsPageSource.match(/async function handleTestProxyConnection\(\)[\s\S]*?\n\}/)

  assert.ok(checkBlock)
  assert.match(checkBlock[0], /openDiagnosticResultDialog\(\{[\s\S]*?正在开启 MITM 代理/)

  const startMitmIndex = checkBlock[0].indexOf('await startMitmProxy()')
  const enableSystemIndex = checkBlock[0].indexOf('await enableSystemProxy()')
  const testProxyIndex = checkBlock[0].indexOf('await testProxyConnection()')
  const disableSystemIndex = checkBlock[0].indexOf('await disableSystemProxy()')
  const stopMitmIndex = checkBlock[0].indexOf('await stopMitmProxy()')

  assert.ok(startMitmIndex > -1)
  assert.ok(enableSystemIndex > startMitmIndex)
  assert.ok(testProxyIndex > enableSystemIndex)
  assert.ok(disableSystemIndex > testProxyIndex)
  assert.ok(stopMitmIndex > disableSystemIndex)
  assert.match(checkBlock[0], /emitTaskStatus\(mitmStartResult\)/)
  assert.match(checkBlock[0], /emitTaskStatus\(systemEnableResult\)/)
  assert.match(checkBlock[0], /emitTaskStatus\(systemDisableResult\)/)
  assert.match(checkBlock[0], /emitTaskStatus\(mitmStopResult\)/)
  assert.match(checkBlock[0], /systemDisableResult\.ok \? \(systemDisableResult\.message \?\? '已关闭'\)/)
})

test('流程测试按钮使用流程名称作为标题，并用说明表达执行范围', () => {
  const flowDiagnosticsBlock = extractSettingsCaseBlock('flow-diagnostics')

  assert.match(flowDiagnosticsBlock, /label: '窗口点击流程'/)
  assert.match(flowDiagnosticsBlock, /buttonLabel: '窗口测试'/)
  assert.match(flowDiagnosticsBlock, /description: '首次立即激活公众号主页，按 UIA 日期组和文章卡片/)
  assert.match(flowDiagnosticsBlock, /showWindowClickFlowOptions: true/)
  assert.match(flowDiagnosticsBlock, /handleWindowClickFlowDiagnosticAction/)
  assert.doesNotMatch(flowDiagnosticsBlock, /handleWindowDiagnosticAction\('first-article-test'\)/)
  assert.doesNotMatch(flowDiagnosticsBlock, /handlePendingDiagnosticAction\('单篇文章流程'\)/)
  assert.match(flowDiagnosticsBlock, /label: '单篇文章详情流程'/)
  assert.match(flowDiagnosticsBlock, /buttonLabel: '详情获取'/)
  assert.match(flowDiagnosticsBlock, /description: '激活主页窗口并读取当前可视区第一篇文章卡片'/)
  assert.match(flowDiagnosticsBlock, /showArticleDetailSkipCollectedOption: true/)
  assert.match(flowDiagnosticsBlock, /label: '初始内容存储测试'/)
  assert.match(flowDiagnosticsBlock, /buttonLabel: '初始内容存储'/)
  assert.match(flowDiagnosticsBlock, /showInitialContentStorageOptions: true/)
  assert.match(settingsPageSource, /const articleDetailSkipCollectedRecords = ref\(false\)/)
  assert.match(settingsPageSource, /const initialContentStorageSkipCollectedRecords = ref\(false\)/)
  assert.match(settingsPageSource, /const initialContentStorageStoreArticleDetail = ref\(true\)/)
  assert.match(settingsPageSource, /const articleDetailCommentsSkipCollectedRecords = ref\(false\)/)
  assert.match(settingsPageSource, /const articleDetailCommentsStoreArticleDetail = ref\(true\)/)
  assert.match(settingsPageSource, /const articleDetailCommentsStoreCommentInfo = ref\(true\)/)
  assert.match(settingsPageSource, /const articleDetailOfflineCacheStateful = ref\(false\)/)
  assert.match(settingsPageSource, /class="article-detail-skip-option"/)
  assert.match(settingsPageSource, /v-model:checked="articleDetailSkipCollectedRecords"/)
  assert.match(settingsPageSource, /v-model:checked="initialContentStorageSkipCollectedRecords"/)
  assert.match(settingsPageSource, /v-model:checked="initialContentStorageStoreArticleDetail"/)
  assert.match(settingsPageSource, /aria-label="初始内容存储文章详情"/)
  assert.match(settingsPageSource, /storeArticleDetail: initialContentStorageStoreArticleDetail\.value/)
  assert.match(pythonApiSource, /export type InitialContentStorageDiagnosticOptions = \{/)
  assert.match(pythonApiSource, /skipCollectedRecords\?: boolean/)
  assert.match(pythonApiSource, /storeArticleDetail\?: boolean/)
  assert.match(flowDiagnosticsBlock, /label: '单篇评论存储测试'/)
  assert.match(flowDiagnosticsBlock, /buttonLabel: '评论信息存储'/)
  assert.match(flowDiagnosticsBlock, /description: '复用初始内容存储，随后启动独立评论子进程采集评论'/)
  assert.match(flowDiagnosticsBlock, /showArticleDetailCommentsOptions: true/)
  assert.match(settingsPageSource, /v-model:checked="articleDetailCommentsSkipCollectedRecords"/)
  assert.match(settingsPageSource, /v-model:checked="articleDetailCommentsStoreArticleDetail"/)
  assert.match(settingsPageSource, /v-model:checked="articleDetailCommentsStoreCommentInfo"/)
  assert.match(settingsPageSource, /aria-label="详情评论跳过已采集记录"/)
  assert.match(settingsPageSource, /aria-label="详情评论存储文章详情"/)
  assert.match(settingsPageSource, /aria-label="详情评论存储评论信息"/)
  assert.match(settingsPageSource, /v-model:checked="articleDetailCommentsStoreArticleDetail"[\s\S]*?\n\s+disabled\n[\s\S]*?aria-label="详情评论存储文章详情"/)
  assert.match(settingsPageSource, /v-model:checked="articleDetailCommentsStoreCommentInfo"[\s\S]*?\n\s+disabled\n[\s\S]*?aria-label="详情评论存储评论信息"/)
  assert.match(settingsPageSource, /class="article-detail-comments-option-stack"/)
  assert.match(settingsPageSource, /article-detail-comments-option-action-control/)
  assert.match(flowDiagnosticsBlock, /label: '单篇离线缓存测试'/)
  assert.match(flowDiagnosticsBlock, /buttonLabel: '离线缓存'/)
  assert.match(flowDiagnosticsBlock, /showArticleDetailOfflineCacheOptions: true/)
  assert.match(settingsPageSource, /startArticleDetailOfflineCacheDiagnostic/)
  assert.match(settingsPageSource, /getArticleDetailOfflineCacheDiagnostic/)
  assert.match(settingsPageSource, /v-model:checked="articleDetailOfflineCacheSkipCollectedRecords"/)
  assert.match(settingsPageSource, /v-model:checked="articleDetailOfflineCacheStateful"/)
  assert.match(settingsPageSource, /class="article-detail-offline-cache-option-stack"[\s\S]*?v-model:checked="articleDetailOfflineCacheSkipCollectedRecords"[\s\S]*?v-model:checked="articleDetailOfflineCacheStateful"/)
  assert.match(settingsPageSource, /article-detail-offline-cache-option-action-control/)
  assert.match(
    settingsPageSource,
    /\.settings-config-control\.compact-control\.article-detail-offline-cache-option-action-control \{[\s\S]*?grid-template-columns:\s*max-content max-content max-content;/,
  )
  assert.match(settingsPageSource, /v-model:checked="articleDetailOfflineCacheStoreArticleDetail"/)
  assert.match(settingsPageSource, /v-model:checked="articleDetailOfflineCacheArchiveContent"/)
  assert.match(settingsPageSource, /aria-label="离线缓存跳过已采集记录"/)
  assert.match(settingsPageSource, /aria-label="离线缓存带状态"/)
  assert.match(settingsPageSource, />\s*带状态（beta）\s*</)
  assert.match(settingsPageSource, /aria-label="离线缓存存储文章详情"/)
  assert.match(settingsPageSource, /aria-label="离线缓存归档内容"/)
  assert.match(settingsPageSource, /statefulOfflineCache: articleDetailOfflineCacheStateful\.value/)
  assert.match(settingsPageSource, /archiveOfflineContent: articleDetailOfflineCacheArchiveContent\.value/)
  assert.match(pythonApiSource, /export type ArticleDetailOfflineCacheDiagnosticOptions = \{/)
  assert.match(pythonApiSource, /archiveOfflineContent\?: boolean/)
  assert.match(pythonApiSource, /statefulOfflineCache\?: boolean/)
  assert.match(pythonApiSource, /article-detail-offline-cache/)
  const flowDiagnosticTones = [...flowDiagnosticsBlock.matchAll(/tone: '([^']+)'/g)]
    .map((match) => match[1])
  assert.deepEqual(flowDiagnosticTones, ['blue', 'purple', 'success', 'orange', 'primary'])
  assert.doesNotMatch(flowDiagnosticsBlock, /label: '单篇文章全内容'/)
  assert.doesNotMatch(flowDiagnosticsBlock, /label: '单次主流程全量获取'/)
  assert.doesNotMatch(flowDiagnosticsBlock, /buttonLabel: '主流程获取'/)
  assert.doesNotMatch(flowDiagnosticsBlock, /handlePendingDiagnosticAction\('单次主流程全量获取'\)/)
  assert.doesNotMatch(flowDiagnosticsBlock, /label: '窗口测试'/)
  assert.doesNotMatch(flowDiagnosticsBlock, /label: '详情获取'/)
  assert.doesNotMatch(flowDiagnosticsBlock, /label: '详情评论'/)
  assert.doesNotMatch(flowDiagnosticsBlock, /label: '主流程获取'/)
  assert.match(settingsPageSource, /buttonLabel\?: string/)
  assert.match(settingsPageSource, /\{\{ action\.buttonLabel \?\? action\.label \}\}/)
})

test('窗口点击流程使用独立实时任务接口并在弹窗中提供立即停止', () => {
  assert.match(settingsPageSource, /startWindowClickFlowDiagnostic/)
  assert.match(settingsPageSource, /getWindowClickFlowDiagnostic/)
  assert.match(settingsPageSource, /stopWindowClickFlowDiagnostic/)
  assert.match(settingsPageSource, /isWindowClickFlowDiagnosticRunning/)
  assert.match(settingsPageSource, /activeWindowClickFlowJobId/)
  assert.match(settingsPageSource, /function handleDiagnosticResultBackdropClick/)
  assert.match(settingsPageSource, /@click\.self="handleDiagnosticResultBackdropClick"/)
  assert.match(settingsPageSource, /立即停止/)
  assert.match(settingsPageSource, /stopActiveWindowClickFlowDiagnostic/)
})

test('窗口操作诊断按钮接入真实窗口诊断接口并使用最新命名', () => {
  const windowDiagnosticsBlock = extractSettingsCaseBlock('window-diagnostics')

  assert.match(settingsPageSource, /runWindowDiagnosticAction/)
  assert.match(settingsPageSource, /async function handleWindowDiagnosticAction\(/)
  assert.match(settingsPageSource, /openDiagnosticResultDialog\(\{[\s\S]*?正在执行窗口诊断/)
  assert.match(windowDiagnosticsBlock, /label: '读取主页'/)
  assert.match(windowDiagnosticsBlock, /label: '首篇点击'/)
  assert.match(windowDiagnosticsBlock, /description: '立刻聚焦主页窗口，找到首篇候选文章并点击打开；不等待标题确认，也不关闭文章标签。'/)
  assert.match(windowDiagnosticsBlock, /label: '回弹滚动'/)
  assert.doesNotMatch(windowDiagnosticsBlock, /label: '首篇测试'/)
  assert.doesNotMatch(windowDiagnosticsBlock, /label: '关闭全部'/)
  assert.doesNotMatch(windowDiagnosticsBlock, /label: '点击首篇'/)
  assert.doesNotMatch(windowDiagnosticsBlock, /label: '回滚滚动'/)
  for (const action of [
    'read-home',
    'activate-home',
    'first-article-click',
    'scroll-page',
    'bounce-scroll',
    'close-tab',
  ]) {
    assert.match(windowDiagnosticsBlock, new RegExp("handleWindowDiagnosticAction\\('" + action + "'"))
  }
  assert.ok(
    windowDiagnosticsBlock.indexOf("label: '读取主页'") < windowDiagnosticsBlock.indexOf("label: '激活主页'"),
    '读取主页应显示在激活主页上方',
  )
  assert.doesNotMatch(windowDiagnosticsBlock, /handleWindowDiagnosticAction\('first-article-test'\)/)
  assert.doesNotMatch(windowDiagnosticsBlock, /handleWindowDiagnosticAction\('close-all-tabs'\)/)
  assert.doesNotMatch(windowDiagnosticsBlock, /handlePendingDiagnosticAction\('微信主页窗口激活'\)/)
  assert.doesNotMatch(windowDiagnosticsBlock, /handlePendingDiagnosticAction\('点击可见区第一篇文章'\)/)
})

test('滚动页面诊断提供独立步长输入并随请求发送', () => {
  const windowDiagnosticsBlock = extractSettingsCaseBlock('window-diagnostics')
  const runtimeConfigApplyBlock = settingsPageSource.match(
    /function applyRuntimeConfigValues\([\s\S]*?(?=\nfunction replaceRuntimeConfigValues)/,
  )?.[0] ?? ''

  assert.match(windowDiagnosticsBlock, /label: '滚动页面'[\s\S]*?showScrollStepInput: true/)
  assert.match(settingsPageSource, /const windowDiagnosticScrollSteps = ref\(3\)/)
  assert.match(settingsPageSource, /aria-label="滚动页面步长"/)
  assert.match(settingsPageSource, /min="1"/)
  assert.match(settingsPageSource, /max="200"/)
  assert.match(settingsPageSource, /scrollSteps: normalizeWindowDiagnosticScrollSteps\(\)/)
  assert.doesNotMatch(runtimeConfigApplyBlock, /windowDiagnosticScrollSteps/)
  assert.match(
    pythonApiSource,
    /runWindowDiagnosticAction\([\s\S]*?options: WindowDiagnosticOptions = \{\}[\s\S]*?\{ action, \.\.\.options \}/,
  )
})

test('配置详情说明下方展示 custom.yaml 变量路径', () => {
  const keylineStyle = settingsPageSource.match(/^\.settings-config-keyline \{[\s\S]*?^\}/m)?.[0] ?? ''

  assert.match(settingsPageSource, /function getSettingsConfigKeyPath\(configKey\?: string\)/)
  assert.match(settingsPageSource, /configKey\.split\('\.'\)\.join\('\\u00A0-->\\u00A0'\)/)
  assert.match(settingsPageSource, /v-if="control\.configKey" class="settings-config-keyline"/)
  assert.match(settingsPageSource, /class="settings-config-keyline">\{\{ getSettingsConfigKeyPath\(field\.configKey\) \}\}<\/code>/)
  assert.match(keylineStyle, /font-size:\s*12\.5px;/)
  assert.match(keylineStyle, /white-space:\s*normal;/)
  assert.match(keylineStyle, /overflow-wrap:\s*break-word;/)
  assert.doesNotMatch(keylineStyle, /text-overflow:\s*ellipsis;/)
  assert.match(settingsPageSource, /configKey: 'basic_settings\.runtime_maintenance\.log_level'/)
  assert.match(settingsPageSource, /configKey: 'basic_settings\.proxy_settings\.host'/)
  assert.match(settingsPageSource, /configKey: 'basic_settings\.database_settings\.data_schema_version'/)
})

test('数字配置项把单位合并到左侧标题，右侧控件不再单独渲染单位', () => {
  assert.match(settingsPageSource, /function getSettingsFieldLabel\(field: SettingsDetailField\)/)
  assert.match(settingsPageSource, /field\.unit \?/)
  assert.match(settingsPageSource, /field\.label/)
  assert.match(settingsPageSource, /<strong>\{\{ getSettingsFieldLabel\(field\) \}\}<\/strong>/)
  assert.doesNotMatch(settingsPageSource, /<span v-if="field\.unit" class="settings-field-unit">/)

  for (const blockName of ['single-mitm-capture', 'single-article-tab', 'main-home-window', 'main-home-scroll', 'main-dispatch-control', 'single-html-storage', 'single-comment-collection', 'single-offline-cache']) {
    const block = extractSettingsCaseBlock(blockName)
    assert.match(block, /inputType: 'number-stepper'[^}]*unit: '[^']+'/)
  }
})

test('设置页展示的配置变量名都来自 custom.yaml', () => {
  const yamlKeys = collectYamlLeafKeys(customYamlSource)
  const displayedKeys = [
    ...settingsPageSource.matchAll(/configKey:\s*'([^']+)'/g),
    ...settingsPageSource.matchAll(/<span class="config-field-key">([^<]+)<\/span>/g),
  ].map((match) => match[1].trim())
  const extraKeys = [...new Set(displayedKeys.filter((key) => !yamlKeys.has(key)))].sort()

  assert.deepEqual(extraKeys, [])
})

test('基础设置、主流程和单篇任务完整展示 custom.yaml 的新配置路径', () => {
  const expectedKeys = [
    'basic_settings.project_storage.article_storage_root',
    'basic_settings.project_storage.temp_dir',
    'basic_settings.project_storage.log_dir',
    'basic_settings.database_settings.data_schema_version',
    'basic_settings.database_settings.db_dir',
    'basic_settings.runtime_maintenance.log_level',
    'basic_settings.runtime_maintenance.auto_clean_temp_files',
    'basic_settings.runtime_maintenance.temp_retention_days',
    'basic_settings.runtime_maintenance.log_retention_days',
    'basic_settings.proxy_settings.host',
    'basic_settings.proxy_settings.port',
    'basic_settings.proxy_settings.verification_url',
    'basic_settings.proxy_settings.confdir',
    'basic_settings.proxy_settings.ca_cert_path',
    'basic_settings.proxy_settings.startup_delay_seconds',
    'basic_settings.proxy_settings.enable_system_proxy',
    'basic_settings.proxy_settings.ssl_insecure',
    'main_flow.home_window.activation_wait_seconds',
    'main_flow.home_window.home_find_timeout_seconds',
    'main_flow.home_scroll.date_seek_scroll_steps_range',
    'main_flow.home_scroll.scroll_initial_delay_seconds',
    'main_flow.home_scroll.scroll_probe_interval_seconds_range',
    'main_flow.home_scroll.unchanged_before_bounce_seconds',
    'main_flow.home_scroll.lazy_load_timeout_seconds',
    'main_flow.home_scroll.bounce_enabled',
    'main_flow.home_scroll.bounce_attempts',
    'main_flow.home_scroll.bounce_up_steps',
    'main_flow.home_scroll.bounce_pause_seconds',
    'main_flow.home_scroll.bounce_down_steps',
    'main_flow.dispatch_control.single_task_interval_seconds',
    'single_article_task.article_tab.restore_focus_after_close',
    'single_article_task.article_tab.article_open_timeout_seconds',
    'single_article_task.article_tab.article_title_poll_interval_seconds_range',
    'single_article_task.article_tab.article_title_stable_delay_seconds',
    'single_article_task.article_tab.article_close_confirm_timeout_seconds',
    'single_article_task.mitm_capture.ready_timeout_seconds',
    'single_article_task.mitm_capture.capture_timeout_seconds',
    'single_article_task.mitm_capture.result_timeout_seconds',
    'single_article_task.mitm_capture.listener_shutdown_timeout_seconds',
    'single_article_task.mitm_capture.close_as_capture_deadline',
    'single_article_task.html_storage.request_timeout_seconds',
    'single_article_task.comment_collection.enabled_by_default',
    'single_article_task.comment_collection.request_timeout_seconds',
    'single_article_task.comment_collection.page_interval_seconds',
    'single_article_task.comment_collection.top_level_max_pages',
    'single_article_task.comment_collection.max_concurrent_processes',
    'single_article_task.offline_cache.enabled_by_default',
    'single_article_task.offline_cache.max_scroll_seconds',
    'single_article_task.offline_cache.resource_timeout_seconds',
    'single_article_task.offline_cache.max_concurrent_processes',
  ]

  for (const configKey of expectedKeys) {
    assert.match(settingsPageSource, new RegExp(configKey.replaceAll('.', '\\.'), 'g'), `${configKey} 应在设置页展示`)
  }
})

test('目录和路径类配置值只允许选中复制，目录变更从浏览按钮进入', () => {
  assert.match(settingsPageSource, /readonly/)
  assert.match(settingsPageSource, /@focus="selectReadonlyInputText"/)
  assert.match(settingsPageSource, /@click="selectReadonlyInputText"/)
  assert.match(settingsPageSource, /@paste\.prevent/)
  assert.match(settingsPageSource, /@cut\.prevent/)
  assert.match(settingsPageSource, /@drop\.prevent/)
  assert.match(settingsPageSource, /browseAction: handlePendingBrowseAction/)
  assert.match(settingsPageSource, /@click="handlePendingBrowseAction\(field\)"/)
})

test('项目存储详情不再展示项目工作目录配置块', () => {
  const projectStorageBlock = settingsPageSource.match(/case 'project-storage':[\s\S]*?case 'database-storage':/)

  assert.ok(projectStorageBlock)
  assert.doesNotMatch(projectStorageBlock[0], /configKey: 'project\.root'/)
  assert.doesNotMatch(projectStorageBlock[0], /label: '项目工作目录'/)
})

test('运行维护详情不再展示软件版本配置块', () => {
  const runtimeMaintenanceBlock = extractSettingsCaseBlock('runtime-maintenance')

  assert.doesNotMatch(runtimeMaintenanceBlock, /configKey: 'software\.version'/)
  assert.doesNotMatch(runtimeMaintenanceBlock, /label: '软件版本'/)
})

test('数据库存储详情只保留数据表结构版本和数据库目录', () => {
  const databaseStorageBlock = extractSettingsCaseBlock('database-storage')

  assert.doesNotMatch(settingsPageSource, /storage\.db_file_name/)
  assert.doesNotMatch(databaseStorageBlock, /configKey: 'sqlite\.version'/)
  assert.doesNotMatch(databaseStorageBlock, /label: '数据库版本'/)
  assert.doesNotMatch(databaseStorageBlock, /configKey: 'storage\.db_file_name'/)
  assert.doesNotMatch(databaseStorageBlock, /label: '数据库文件'/)
  assert.match(databaseStorageBlock, /configKey: 'basic_settings\.database_settings\.data_schema_version'/)
  assert.match(databaseStorageBlock, /configKey: 'basic_settings\.database_settings\.db_dir'/)
})

test('代理基础信息中的 mitmproxy 目录和 CA 证书路径为只读配置', () => {
  const proxyBasicBlock = extractSettingsCaseBlock('proxy-basic')

  for (const configKey of ['basic_settings.proxy_settings.confdir', 'basic_settings.proxy_settings.ca_cert_path']) {
    const fieldBlock = proxyBasicBlock.match(new RegExp("configKey: '" + configKey.replace('.', "\\.") + "'[^}]*}"))

    assert.ok(fieldBlock, `${configKey} 字段应存在`)
    assert.match(fieldBlock[0], /tone: 'readonly'/)
    assert.doesNotMatch(fieldBlock[0], /browseAction|browseLabel/)
  }
})

test('MITM 设置使用秒单位、开关和加减数字框表达可调项', () => {
  const mitmBlock = extractSettingsCaseBlock('single-mitm-capture')

  assert.match(mitmBlock, /label: '代理启动额外等待（秒）'/)
  assert.match(mitmBlock, /configKey: 'basic_settings\.proxy_settings\.startup_delay_seconds'/)
  assert.match(mitmBlock, /configKey: 'basic_settings\.proxy_settings\.ssl_insecure'[^}]*inputType: 'switch'/)
  assert.match(mitmBlock, /configKey: 'single_article_task\.mitm_capture\.ready_timeout_seconds'[^}]*inputType: 'number-stepper'[^}]*unit: '秒'/)
  assert.match(mitmBlock, /configKey: 'single_article_task\.mitm_capture\.capture_timeout_seconds'[^}]*inputType: 'number-stepper'[^}]*unit: '秒'/)
  assert.match(mitmBlock, /configKey: 'single_article_task\.mitm_capture\.close_as_capture_deadline'[^}]*inputType: 'switch'/)
})

test('运行维护不再展示任务间隔和单篇文章重试次数', () => {
  const runtimeBlock = extractSettingsCaseBlock('runtime-maintenance')

  assert.doesNotMatch(runtimeBlock, /basic_settings\.runtime_maintenance\.request_interval_seconds/)
  assert.match(settingsPageSource, /configKey: 'main_flow\.dispatch_control\.single_task_interval_seconds'[^}]*inputType: 'number-stepper'[^}]*unit: '秒'/)
  assert.doesNotMatch(settingsPageSource, /basic_settings\.runtime_maintenance\.article_retry_count/)
  assert.doesNotMatch(settingsPageSource, /retryCount/)
})

test('单篇标签操作使用 single_article_task 键、开关和带单位的加减数字框', () => {
  const singleTabBlock = extractSettingsCaseBlock('single-article-tab')

  assert.match(singleTabBlock, /configKey: 'single_article_task\.article_tab\.restore_focus_after_close'[^}]*inputType: 'switch'/)

  for (const [configKey, unit] of [
    ['single_article_task.article_tab.article_title_stable_delay_seconds', '秒'],
    ['single_article_task.article_tab.article_open_timeout_seconds', '秒'],
    ['single_article_task.article_tab.article_close_confirm_timeout_seconds', '秒'],
  ]) {
    const escapedKey = configKey.replaceAll('.', '\\.')
    assert.match(singleTabBlock, new RegExp("configKey: '" + escapedKey + "'[^}]*inputType: 'number-stepper'[^}]*unit: '" + unit + "'"))
  }
  assert.match(singleTabBlock, /configKey: 'single_article_task\.article_tab\.article_title_poll_interval_seconds_range'[\s\S]*?inputType: 'readonly-range'[\s\S]*?unit: '秒'/)
  assert.doesNotMatch(singleTabBlock, /article_title_poll_growth_factor/)
  assert.doesNotMatch(singleTabBlock, /article_close_title_poll_interval_seconds/)
})

test('主页窗口操作使用 main_flow 键和秒单位加减数字框', () => {
  const homeWindowBlock = extractSettingsCaseBlock('main-home-window')

  for (const configKey of [
    'main_flow.home_window.activation_wait_seconds',
    'main_flow.home_window.home_find_timeout_seconds',
  ]) {
    const escapedKey = configKey.replaceAll('.', '\\.')
    assert.match(homeWindowBlock, new RegExp("configKey: '" + escapedKey + "'[^}]*inputType: 'number-stepper'[^}]*unit: '秒'"))
  }
  assert.doesNotMatch(homeWindowBlock, /home_find_use_article_probe/)
  assert.doesNotMatch(homeWindowBlock, /screen_click_wait_seconds/)
  assert.doesNotMatch(homeWindowBlock, /click_mouse_move_wait_seconds/)
  assert.doesNotMatch(homeWindowBlock, /uia_control_click_wait_seconds/)
})

test('主页滚动操作使用 main_flow 键、开关和步数/次数/秒单位', () => {
  const homeScrollBlock = extractSettingsCaseBlock('main-home-scroll')

  assert.match(homeScrollBlock, /configKey: 'main_flow\.home_scroll\.bounce_enabled'[^}]*inputType: 'switch'/)

  for (const [configKey, unit] of [
    ['main_flow.home_scroll.scroll_initial_delay_seconds', '秒'],
    ['main_flow.home_scroll.unchanged_before_bounce_seconds', '秒'],
    ['main_flow.home_scroll.lazy_load_timeout_seconds', '秒'],
    ['main_flow.home_scroll.bounce_up_steps', '步'],
    ['main_flow.home_scroll.bounce_pause_seconds', '秒'],
    ['main_flow.home_scroll.bounce_down_steps', '步'],
    ['main_flow.home_scroll.bounce_attempts', '次'],
  ]) {
    const escapedKey = configKey.replaceAll('.', '\\.')
    assert.match(homeScrollBlock, new RegExp("configKey: '" + escapedKey + "'[^}]*inputType: 'number-stepper'[^}]*unit: '" + unit + "'"))
  }
  assert.match(homeScrollBlock, /configKey: 'main_flow\.home_scroll\.date_seek_scroll_steps_range'[\s\S]*?inputType: 'readonly-range'[\s\S]*?unit: '步'/)
  assert.match(homeScrollBlock, /configKey: 'main_flow\.home_scroll\.scroll_probe_interval_seconds_range'[\s\S]*?inputType: 'readonly-range'[\s\S]*?unit: '秒'/)
  assert.doesNotMatch(homeScrollBlock, /max_scroll_attempts/)
  assert.doesNotMatch(homeScrollBlock, /scroll_probe_growth_factor/)
  assert.doesNotMatch(homeScrollBlock, /scroll_settle_timeout_seconds/)
})

test('单篇任务设置中的开关和数值项使用统一控件样式', () => {
  const referenceBlock = extractSettingsCaseBlock('single-html-storage')
  const commentBlock = extractSettingsCaseBlock('single-comment-collection')
  const offlineBlock = extractSettingsCaseBlock('single-offline-cache')

  assert.doesNotMatch(settingsPageSource, /data_acquisition\.initial_html/)
  assert.match(referenceBlock, /configKey: 'single_article_task\.html_storage\.request_timeout_seconds'[^}]*inputType: 'number-stepper'[^}]*unit: '秒'/)
  assert.match(commentBlock, /configKey: 'single_article_task\.comment_collection\.enabled_by_default'[^}]*inputType: 'switch'/)
  assert.match(commentBlock, /configKey: 'single_article_task\.comment_collection\.request_timeout_seconds'[^}]*inputType: 'number-stepper'[^}]*unit: '秒'/)
  assert.match(commentBlock, /configKey: 'single_article_task\.comment_collection\.page_interval_seconds'[^}]*inputType: 'number-stepper'[^}]*unit: '秒'/)
  assert.match(commentBlock, /configKey: 'single_article_task\.comment_collection\.top_level_max_pages'[^}]*inputType: 'number-stepper'[^}]*unit: '页'/)
  assert.doesNotMatch(commentBlock, /reply_max_pages/)
  assert.match(commentBlock, /configKey: 'single_article_task\.comment_collection\.max_concurrent_processes'[^}]*inputType: 'number-stepper'[^}]*unit: '个'/)
  assert.match(offlineBlock, /configKey: 'single_article_task\.offline_cache\.enabled_by_default'[^}]*inputType: 'switch'/)
  assert.match(offlineBlock, /configKey: 'single_article_task\.offline_cache\.max_scroll_seconds'[^}]*inputType: 'number-stepper'[^}]*unit: '秒'/)
  assert.match(offlineBlock, /configKey: 'single_article_task\.offline_cache\.resource_timeout_seconds'[^}]*inputType: 'number-stepper'[^}]*unit: '秒'/)
  assert.match(offlineBlock, /configKey: 'single_article_task\.offline_cache\.max_concurrent_processes'[^}]*inputType: 'number-stepper'[^}]*unit: '个'/)
})

test('短控件配置项在说明右侧展示，长路径类配置保持宽行展示', () => {
  assert.match(settingsPageSource, /getSettingsControlLayoutClass/)
  assert.match(settingsPageSource, /getSettingsFieldLayoutClass/)
  assert.match(settingsPageSource, /compact-control/)
  assert.match(settingsPageSource, /wide-control/)
  assert.match(settingsPageSource, /:class="\['settings-config-control', getSettingsControlLayoutClass\(control\)\]"/)
  assert.match(settingsPageSource, /:class="\['settings-config-control', getSettingsFieldLayoutClass\(field\)\]"/)
  assert.match(
    settingsPageSource,
    /\.settings-config-row\.compact-control \{[\s\S]*?grid-template-columns:\s*minmax\(0, 1fr\) max-content;/,
  )
  assert.match(
    settingsPageSource,
    /\.settings-config-row\.compact-control \{[\s\S]*?align-items:\s*start;/,
  )
  assert.match(
    settingsPageSource,
    /\.settings-config-row\.wide-control \{[\s\S]*?grid-template-columns:\s*minmax\(0, 1fr\);/,
  )
  assert.match(
    settingsPageSource,
    /\.settings-config-control\.compact-control \{[\s\S]*?justify-self:\s*end;/,
  )
  assert.match(
    settingsPageSource,
    /\.settings-config-control\.compact-control \{[\s\S]*?align-self:\s*start;/,
  )
  assert.match(
    settingsPageSource,
    /\.settings-config-row\.compact-control \.settings-config-keyline \{[\s\S]*?grid-column:\s*1 \/ -1;[\s\S]*?grid-row:\s*2;/,
  )
  assert.match(
    settingsPageSource,
    /\.settings-config-row\.compact-control \.settings-config-copy \{[\s\S]*?grid-column:\s*1;[\s\S]*?grid-row:\s*1;/,
  )
  assert.doesNotMatch(
    settingsPageSource,
    /\.settings-config-row\.compact-control \.settings-config-copy \{[\s\S]*?display:\s*contents;/,
  )
  assert.match(
    settingsPageSource,
    /\.settings-config-control\.compact-control \{[\s\S]*?grid-column:\s*2;[\s\S]*?grid-row:\s*1;/,
  )
  assert.match(
    settingsPageSource,
    /<div class="settings-config-copy">[\s\S]*?<\/div>\s*<code class="settings-config-keyline">\{\{ getSettingsConfigKeyPath\(field\.configKey\) \}\}<\/code>\s*<div :class="\['settings-config-control', getSettingsFieldLayoutClass\(field\)\]">/,
  )
  assert.match(
    settingsPageSource,
    /\.settings-config-control\.wide-control \{[\s\S]*?grid-template-columns:\s*minmax\(0, 1fr\) auto auto;/,
  )
})

test('三段式配置中心覆盖 custom.yaml 的主要配置分组', () => {
  for (const label of [
    '基础设置',
    '主流程',
    '单篇任务',
    '诊断工具',
  ]) {
    assert.match(settingsPageSource, new RegExp(label))
  }

  for (const itemKey of [
    'project-storage',
    'database-storage',
    'runtime-maintenance',
    'proxy-basic',
    'main-home-window',
    'main-home-scroll',
    'main-dispatch-control',
    'single-article-tab',
    'single-mitm-capture',
    'single-html-storage',
    'single-comment-collection',
    'single-offline-cache',
    'mitm-diagnostics',
    'window-diagnostics',
    'flow-diagnostics',
  ]) {
    assert.match(settingsPageSource, new RegExp("key: '" + itemKey + "'"))
  }

  assert.match(settingsPageSource, /MITM 捕获/)
  assert.match(settingsPageSource, /单篇标签操作/)
  assert.match(settingsPageSource, /主页窗口/)
  assert.match(settingsPageSource, /主页滚动/)
  assert.match(settingsPageSource, /诊断工具/)
  assert.match(settingsPageSource, /diagnostic-action-grid/)
  assert.doesNotMatch(settingsPageSource, /key: 'runtime-environment'/)
})

test('设置类别将诊断工具显示在第一项', () => {
  assert.match(
    settingsPageSource,
    /const settingsCategories: SettingsCategory\[\] = \[\s*\{\s*key: 'diagnostics'/,
  )
  assert.match(
    settingsPageSource,
    /const selectedSettingsCategoryKey = ref<SettingsCategoryKey>\(settingsCategories\[0\]!\.key\)/,
  )
})

test('系统配置页目录浏览对接系统目录选择接口', () => {
  assert.match(settingsPageSource, /selectRuntimeDirectory/)
  assert.match(settingsPageSource, /updateRuntimeConfig/)
  assert.match(settingsPageSource, /function handlePendingBrowseAction\(field: SettingsDetailField\)/)
  assert.match(settingsPageSource, /handlePendingBrowseAction\(field\)/)
  assert.doesNotMatch(settingsPageSource, /目录选择接口待接入/)
})

test('恢复默认按钮先确认，再使用 system.yaml 覆盖 custom.yaml', () => {
  assert.match(pythonApiSource, /export async function resetRuntimeConfig\(\)/)
  assert.match(pythonApiSource, /postJson<ResetRuntimeConfigResult>\('\/api\/config\/reset'/)
  assert.match(settingsPageSource, /resetDefaultsDialogVisible/)
  assert.match(settingsPageSource, /function handleResetDefaults\(\)[\s\S]*?resetDefaultsDialogVisible\.value = true/)
  assert.match(settingsPageSource, /async function confirmResetDefaults\(\)[\s\S]*?resetRuntimeConfig\(\)/)
  assert.match(settingsPageSource, /<AModal[\s\S]*?v-model:open="resetDefaultsDialogVisible"/)
  assert.match(settingsPageSource, /恢复系统默认配置/)
  assert.match(settingsPageSource, /确认恢复/)
  assert.match(settingsPageSource, /data\/custom\.yaml\.bak/)
})

test('单篇任务设置展示 system.yaml 中的原 HTML 请求超时', () => {
  assert.match(customYamlSource, /html_storage:\s*[\s\S]*?request_timeout_seconds:\s*10\.0/)
  assert.match(settingsPageSource, /key:\s*'single-html-storage'/)
  assert.match(settingsPageSource, /single_article_task\.html_storage\.request_timeout_seconds/)
})

test('快速操作按钮使用 Ant Design Vue 并补齐交互状态', () => {
  assert.match(settingsPageSource, /<AButton[\s\S]*?class="settings-ant-button config-action-button success"/)
  assert.doesNotMatch(
    settingsPageSource.match(/<section class="config-actions page-panel"[\s\S]*?<\/section>/)?.[0] ?? '',
    /<VxeButton/,
  )
  assert.match(
    settingsPageSource,
    /\.config-action-grid :deep\(\.ant-btn\.config-action-button:not\(:disabled\):hover\) \{[\s\S]*?transform:\s*none;[\s\S]*?color:\s*var\(--config-action-hover-color\);[\s\S]*?background:\s*var\(--config-action-hover-bg\);[\s\S]*?box-shadow:\s*none;/,
  )
  assert.match(
    settingsPageSource,
    /\.config-action-grid :deep\(\.ant-btn\.config-action-button:not\(:disabled\):active\) \{[\s\S]*?transform:\s*translateY\(0\);[\s\S]*?background:\s*var\(--config-action-active-bg\);/,
  )
  assert.match(
    settingsPageSource,
    /\.config-action-grid :deep\(\.ant-btn\.config-action-button:focus\) \{[\s\S]*?color:\s*var\(--config-action-color\);[\s\S]*?border-color:\s*var\(--config-action-border\);[\s\S]*?background:\s*var\(--config-action-bg\);/,
  )
  assert.match(
    settingsPageSource,
    /\.config-action-grid :deep\(\.ant-btn\.config-action-button:focus-visible\) \{[\s\S]*?outline:\s*3px solid rgba\(53, 127, 217, 0\.24\);[\s\S]*?outline-offset:\s*2px;/,
  )
  assert.match(
    settingsPageSource,
    /\.config-action-grid :deep\(\.ant-btn\.config-action-button:disabled\) \{[\s\S]*?transform:\s*none;[\s\S]*?opacity:\s*0\.58;[\s\S]*?box-shadow:\s*none;/,
  )
  assert.match(settingsPageSource, /\.config-action-button\.success \{[\s\S]*?--config-action-hover-color:\s*#ffffff;/)
  assert.match(settingsPageSource, /\.config-action-button\.success \{[\s\S]*?--config-action-bg:\s*#35B889;/i)
  assert.match(settingsPageSource, /\.config-action-button\.primary \{[\s\S]*?--config-action-bg:\s*#357FD9;/i)
  assert.match(settingsPageSource, /\.config-action-button\.orange \{[\s\S]*?--config-action-bg:\s*#F28B3C;/i)
  assert.match(settingsPageSource, /\.config-action-button\.danger \{[\s\S]*?--config-action-bg:\s*#D74D4D;/i)
  assert.match(settingsPageSource, /\.config-action-button\.ghost \{[\s\S]*?--config-action-hover-color:\s*#2267B8;/i)
  assert.match(settingsPageSource, /:global\(\.collector-app\.dark \.config-action-grid \.config-action-button\.ghost\) \{[\s\S]*?--config-action-hover-color:\s*#D7EAFF;/i)
  assert.doesNotMatch(settingsPageSource, /:global\(\.dark\) \.config-action-button\.ghost/)
  assert.match(
    settingsPageSource,
    /@media \(prefers-reduced-motion: reduce\) \{[\s\S]*?\.config-action-grid :deep\(\.config-action-button\)[\s\S]*?transition:\s*none;[\s\S]*?transform:\s*none;/,
  )
})

test('系统配置页普通提示统一使用 Ant Design Vue Notification', () => {
  assert.match(settingsPageSource, /import \{ notification \} from 'ant-design-vue'/)
  assert.match(settingsPageSource, /notification\[tone\]\(\{/)
  assert.doesNotMatch(settingsPageSource, /settings-toast-fade/)
  assert.doesNotMatch(settingsPageSource, /class="\['settings-toast'/)
})
