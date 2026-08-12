---
name: Access WeChat Article
description: 本地微信公众号公开文章采集与结构化分析工具的产品型界面设计系统
colors:
  page: "#eaf3fb"
  paper: "#fbfdff"
  paper-soft: "#f3f8fc"
  ink: "#15386f"
  ink-strong: "#0c2d63"
  ink-muted: "#4d6c9f"
  primary-blue: "#2d75d6"
  success-green: "#1f8f69"
  success-soft: "#dff3e8"
  warning-orange: "#df7a35"
  danger-red: "#d9413f"
  accent-purple: "#6651cc"
  dark-page: "#0e1728"
  dark-paper: "#15213a"
  dark-ink: "#dfeaff"
  dark-ink-strong: "#f3f7ff"
  dark-ink-muted: "#aac0df"
typography:
  display:
    fontFamily: "Georgia, 'Times New Roman', 'Noto Serif SC', serif"
    fontSize: "36px"
    fontWeight: 500
    lineHeight: 1.05
    letterSpacing: "0"
  headline:
    fontFamily: "'Microsoft YaHei', 'PingFang SC', 'Segoe UI', system-ui, sans-serif"
    fontSize: "22px"
    fontWeight: 900
    lineHeight: 1.2
    letterSpacing: "0"
  title:
    fontFamily: "'Microsoft YaHei', 'PingFang SC', 'Segoe UI', system-ui, sans-serif"
    fontSize: "18px"
    fontWeight: 900
    lineHeight: 1.2
    letterSpacing: "0"
  body:
    fontFamily: "'Microsoft YaHei', 'PingFang SC', 'Segoe UI', system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 700
    lineHeight: 1.56
    letterSpacing: "0"
  label:
    fontFamily: "'Microsoft YaHei', 'PingFang SC', 'Segoe UI', system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 900
    lineHeight: 1.2
    letterSpacing: "0"
  mono:
    fontFamily: "Consolas, 'SFMono-Regular', monospace"
    fontSize: "14px"
    fontWeight: 700
    lineHeight: 1.4
rounded:
  xs: "5px"
  sm: "6px"
  md: "8px"
  lg: "10px"
  action: "14px"
  pill: "999px"
spacing:
  xs: "6px"
  sm: "8px"
  md: "12px"
  lg: "14px"
  xl: "16px"
  panel: "22px"
components:
  panel:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "18px 22px"
  button-primary:
    backgroundColor: "{colors.primary-blue}"
    textColor: "{colors.paper}"
    rounded: "{rounded.sm}"
    padding: "0 12px"
    height: "38px"
  button-success:
    backgroundColor: "{colors.success-green}"
    textColor: "{colors.paper}"
    rounded: "{rounded.sm}"
    padding: "0 12px"
    height: "38px"
  button-ghost:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.primary-blue}"
    rounded: "{rounded.sm}"
    padding: "0 12px"
    height: "38px"
  input:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "0 12px"
    height: "38px"
  chip-success:
    backgroundColor: "{colors.success-soft}"
    textColor: "{colors.success-green}"
    rounded: "{rounded.pill}"
    padding: "0 10px"
    height: "26px"
---

# Design System: Access WeChat Article

## 1. Overview

**Creative North Star: "科研控制台"**

Access WeChat Article 的界面是一套面向本地科研采集流程的产品型控制台。它要让用户先看清系统状态，再进入配置、采集、历史和数据档案，不追求营销页式的视觉冲击，也不把高影响配置包装成含糊的装饰内容。

当前系统采用浅蓝冷调底色、半透明面板、细边框、浅阴影和 VXE 控件体系，形成“轻量玻璃层”的工作台质感。玻璃感只用于区分层级和容器，不用于制造炫技效果；按钮、输入框、状态标签必须克制且明确。

**Key Characteristics:**
- 产品型界面优先，信息密度高于品牌表达。
- 先给状态，再给操作入口，帮助用户判断是否可以开始采集。
- 半透明面板、浅阴影、细边框是层级语言，不是装饰噪音。
- 关键风险必须同时用文字和状态形态表达，不能只靠颜色。
- 组件形态跟随现有 VXE 控件和系统字体，保持熟悉、稳定、可维护。

## 2. Colors

配色以冷调浅蓝工作台为底，主蓝负责当前选择和主要动作，绿色负责可用、成功和安全状态，橙色和红色只用于提醒与风险。

### Primary
- **Control Blue**: 主要动作、当前选中、链接、图标高亮和进度辅助线。它是操作引导色，不作为大面积装饰色。

### Secondary
- **Research Green**: 成功、可采集、代理已连接、证书可用等安全状态。绿色必须配合文字标签出现。
- **Warning Orange**: 待机、提示、清理缓存、需要注意但未失败的状态。
- **Signal Purple**: 数据占用、归档、次级统计等低频辅助信息，禁止扩大成主色调。

### Tertiary
- **Danger Red**: 失败、危险操作和不可恢复后果。红色只服务风险，不用于普通强调。

### Neutral
- **Console Page**: 页面背景使用浅蓝冷调，提供本地工具的安静环境。
- **Frost Paper**: 面板和输入控件使用高亮纸白与轻微透明叠层。
- **Ink Strong / Ink / Ink Muted**: 标题、正文、辅助信息使用同一蓝色墨色阶，避免灰字在浅蓝背景上发虚。
- **Line / Line Soft**: 分隔线和控件描边使用低透明度蓝灰，保持边界但不抢信息。
- **Dark Mode Tokens**: 暗色模式使用深蓝黑底和浅蓝文字，保留同一语义色，不引入新的品牌方向。

### Named Rules

**The Status-First Color Rule.** 主蓝、绿色、橙色、红色只能表达操作、选择、成功、警告、失败等状态语义，不能作为随机装饰。

**The No Decorative Saturation Rule.** 禁止过亮的饱和色和大面积渐变色块；颜色必须帮助用户理解当前配置是否可靠。

## 3. Typography

**Display Font:** Georgia, Times New Roman, Noto Serif SC，用于顶部英文产品名。  
**Body Font:** Microsoft YaHei, PingFang SC, Segoe UI, system-ui，用于全部产品界面。  
**Label/Mono Font:** Consolas / SFMono-Regular 仅用于日志时间、日志级别和技术值。

**Character:** 字体系统以系统 sans 为主，粗字重承担扫描效率。唯一的 serif 出现在品牌标题，不能扩散到表单标签、按钮、数据表或状态文本。

### Hierarchy
- **Display** (500, 36px, 1.05): 只用于顶部 `Access WeChat Article` 品牌名。
- **Headline** (900, 22px, 1.2): 用于主卡片标题、任务区域标题和重要区块标题。
- **Title** (900, 18px, 1.2): 用于侧边导航组、顶部状态条和较小面板标题。
- **Body** (700-800, 14px, 1.56): 用于说明文字、表格、日志、设置说明和普通控件内容。
- **Label** (900, 13-14px, 1.2): 用于表单标签、状态标签、按钮文字和可点击操作。
- **Mono** (700, 14px, 1.4): 用于日志时间、日志级别、端口、路径和技术标识。

### Named Rules

**The Product Sans Rule.** 除顶部品牌名外，界面标签、按钮、数据、表格和配置项一律使用产品 sans 字体栈。

**The Fixed Scale Rule.** 产品界面不使用流式大字号；字号保持固定，优先保证桌面工具里的对齐、扫描和可预测性。

## 4. Elevation

系统采用轻量玻璃层：面板使用 8px 圆角、1px 半透明边框、内高光、浅投影和 `backdrop-filter` 建立层级。阴影是结构性的，不是装饰性的；无玻璃能力或减少透明偏好时必须回退为实色纸白背景。

### Shadow Vocabulary
- **Panel Frost** (`inset 0 1px 0 var(--frost-highlight), inset 0 -1px 0 var(--frost-inner), 0 9px 18px var(--frost-shadow)`): 主面板、侧栏、状态卡、数据卡使用。
- **Compact Panel** (`inset 0 1px 0 rgba(255,255,255,0.72), 0 4px 10px rgba(35,69,111,0.08)`): 系统配置页的小型面板使用。
- **Control Inset** (`inset 0 1px 0 rgba(255,255,255,0.6)`): 输入框、选择框、只读路径框使用。
- **Action Lift** (`0 8px 14px rgba(38,70,116,0.12)`): 首页开始/停止大按钮可使用；普通设置按钮不使用大阴影。

### Named Rules

**The Functional Glass Rule.** 玻璃效果只用于容器层级和状态聚合，不允许用作纯装饰背景。

**The Fallback Is Required Rule.** 所有 `backdrop-filter` 面板必须有实色背景回退，并尊重 `prefers-reduced-transparency`。

## 5. Components

### Buttons
- **Shape:** 设置页按钮使用克制的 6px 圆角；首页主控制按钮可使用 14px 圆角；主题切换和导航选中态可使用 pill。
- **Primary:** 蓝色渐变按钮用于主要动作，例如恢复默认、测试连接等清晰命令。
- **Success:** 绿色按钮用于保存配置、确认可执行动作。
- **Warning / Orange:** 橙色按钮用于清理缓存等需要用户注意但不是危险删除的操作。
- **Ghost:** 白色半透明背景、蓝色文字，用于次级操作。
- **Hover / Focus:** Hover 可以轻微提亮或上移 1px；Focus 必须使用清晰 outline，不依赖阴影单独表达。

### Chips
- **Style:** 状态标签使用 pill 或 6px 小圆角，背景为低饱和状态色，文字为同色深色。
- **State:** 成功、警告、危险必须同时有文本；不能只显示彩色圆点。

### Cards / Containers
- **Corner Style:** 通用面板 8px，小型控件 6px，指标图标 10px。
- **Background:** 面板使用轻量玻璃层；设置页小面板使用更实的白色透明面，减少大面积装饰。
- **Shadow Strategy:** 默认使用 Panel Frost 或 Compact Panel，避免边框和超大模糊阴影叠加造成漂浮感。
- **Border:** 1px 蓝灰半透明边框是标准边界。
- **Internal Padding:** 常规面板 18-24px，设置页面板 17-22px，紧凑控件 8-12px。

### Inputs / Fields
- **Style:** 输入框、选择框、数字框高度 38px，6px 圆角，1px 蓝灰边框，半透明白色背景。
- **Focus:** 使用 3px 蓝色低透明 outline，确保键盘操作可见。
- **Disabled / Readonly:** 只读路径框保留边框和文本省略，不降低到不可读透明度。
- **Dropdown:** VXE 下拉框使用 transfer / 高 z-index，避免被面板 overflow 裁剪。

### Navigation
- **Style:** 侧栏导航使用 18px 粗体、54px 高度、pill 活动态。默认态保持透明，hover 使用轻微蓝色底。
- **Active:** 当前页面使用绿色渐变 pill，文字白色，图标继承当前色。
- **Disabled:** 无页面入口可以禁用并降低透明度，但必须保留可读标签。

### Metrics
- **Dashboard Metrics:** 首页数据统计可以使用大号数值和圆形图标，适合任务概览。
- **Settings Metrics:** 系统配置页顶部指标必须更紧凑，标签与值字号差距收敛，避免像营销指标卡。

### Tables
- **Style:** 表格 14px 字号、36px 行高、蓝灰分隔线、表头粗体。数字和操作列右对齐。
- **State:** 状态列使用标签，而不是只靠颜色文字。

## 6. Do's and Don'ts

### Do:
- **Do** 保持“先状态、后配置入口”的页面秩序，让用户先判断是否可以运行任务。
- **Do** 使用 8px 面板圆角、6px 控件圆角、38px 表单控件高度，保持 VXE 控件和自定义控件一致。
- **Do** 在代理、证书、目录、缓存等高影响配置旁提供明确文字，说明作用和后果。
- **Do** 对正文、说明文字和状态文字保持 WCAG AA 可读性目标。
- **Do** 为减少透明和减少动态效果偏好提供回退。

### Don't:
- **Don't** 使用营销页式大标题、过度装饰、重复卡片堆叠。
- **Don't** 使用过亮的饱和色或无语义的大面积渐变。
- **Don't** 把代理、证书、目录等高影响配置做成含糊的装饰性内容。
- **Don't** 让危险操作只显示按钮而不说明后果。
- **Don't** 在产品界面标签、按钮、数据表中使用 display 字体。
- **Don't** 用颜色单独表达成功、警告或失败；必须同时有文字标签。
- **Don't** 把玻璃面板和阴影用于无意义装饰；层级必须服务阅读和操作。
