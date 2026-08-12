<script setup lang="ts">
import AppIcon from '../components/AppIcon.vue'

type TopbarHealthTone = 'success' | 'warning' | 'danger' | 'info'
type TopbarHealthKey = 'https' | 'ca' | 'proxy-port' | 'storage'

type TopbarHealthItem = {
  key: TopbarHealthKey
  label: string
  value: string
  icon?: string
  statusIcon: string
  tone?: TopbarHealthTone
  checking?: boolean
  disabled?: boolean
}

const props = withDefaults(defineProps<{
  isDark: boolean
  githubUrl?: string
  githubStars?: string
  healthItems?: TopbarHealthItem[]
}>(), {
  githubUrl: 'https://github.com/',
  githubStars: '',
  healthItems: () => [],
})

const emit = defineEmits<{
  toggleTheme: []
  healthCheck: [key: TopbarHealthKey]
}>()
</script>

<template>
  <header class="topbar" aria-label="应用顶部状态栏">
    <div class="brand">
      <img class="brand-logo" src="/favicon.png" alt="Access WeChat Article Logo" />
      <div class="brand-copy">
        <h1>Access WeChat Article</h1>
        <p>数据采集与结构化分析工具</p>
      </div>
    </div>

    <div class="topbar-tools">
      <div class="topbar-health" aria-label="系统健康摘要">
        <button
          v-for="item in props.healthItems"
          :key="item.key"
          type="button"
          :class="[
            'health-item',
            'health-item--' + (item.tone ?? 'info'),
            { 'health-item--checking': item.checking },
          ]"
          :disabled="item.disabled"
          :aria-label="`${item.label}：${item.value}，点击重新检测`"
          :aria-busy="item.checking"
          @click="emit('healthCheck', item.key)"
        >
          <AppIcon v-if="item.icon" class="health-icon" :icon="item.icon" aria-hidden="true" />
          <strong class="health-label">{{ item.label }}</strong>
          <AppIcon class="health-status-icon" :icon="item.statusIcon" aria-hidden="true" />
          <span class="health-value">{{ item.value }}</span>
        </button>
      </div>

      <div class="top-actions">
        <a
          class="github-pill"
          :href="props.githubUrl"
          target="_blank"
          rel="noopener noreferrer"
          aria-label="在 GitHub 打开项目"
        >
          <AppIcon icon="fa-brands fa-github" />
          <span>GitHub</span>
          <span v-if="props.githubStars" class="github-stars">
            <AppIcon icon="fa-solid fa-star" />
            {{ props.githubStars }}
          </span>
          <AppIcon v-else icon="github-open fa-solid fa-arrow-up-right-from-square" />
        </a>

        <button
          :class="['theme-switch', { 'is-dark': props.isDark }]"
          type="button"
          :aria-pressed="props.isDark"
          aria-label="切换明暗主题"
          @click="emit('toggleTheme')"
        >
          <span class="sun"><AppIcon icon="fa-solid fa-sun" /></span>
          <span class="moon"><AppIcon icon="fa-solid fa-moon" /></span>
        </button>
      </div>
    </div>
  </header>
</template>

<style scoped>
.topbar {
  display: grid;
  grid-template-columns: 500px minmax(0, 1fr);
  align-items: center;
  gap: 24px;
  height: 106px;
  margin-bottom: 12px;
}

.brand {
  display: flex;
  align-items: center;
  min-width: 0;
  margin-left: 42px;
}

.brand-logo {
  width: 78px;
  height: 78px;
  flex: 0 0 auto;
  object-fit: contain;
  object-position: center;
  mix-blend-mode: normal;
}

.brand-copy {
  min-width: max-content;
  margin-left: 12px;
}

.brand h1 {
  margin: 0;
  font-family: Georgia, 'Times New Roman', 'Noto Serif SC', serif;
  font-size: 36px;
  line-height: 1.05;
  font-weight: 500;
  letter-spacing: 0;
  color: var(--ink-strong);
  white-space: nowrap;
}

.brand p {
  margin: 9px 0 0;
  font-size: 17px;
  font-weight: 400;
  letter-spacing: 0;
  color: var(--ink);
}

.topbar-tools {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  box-sizing: border-box;
  width: 100%;
  gap: 12px;
  min-width: 0;
  margin-left: 0;
  margin-right: 0;
  padding-right: 28px;
}

.topbar-health {
  display: contents;
}

.health-item {
  --health-state-color: #15386f;

  position: relative;
  isolation: isolate;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  flex: 0 0 auto;
  width: auto;
  min-width: max-content;
  height: 48px;
  padding: 0 12px;
  overflow: hidden;
  border: 1px solid rgba(104, 141, 181, 0.3);
  border-radius: 10px;
  color: var(--ink);
  background: var(--frost-bg-strong);
  box-shadow: var(--paper-shadow-sm);
  cursor: pointer;
  transition: border-color 160ms ease, box-shadow 160ms ease, transform 160ms ease;
  white-space: nowrap;
}

.health-item::before,
.github-pill::before,
.theme-switch::before {
  content: '';
  position: absolute;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  background: var(--paper-fiber);
  opacity: calc(var(--paper-card-texture-opacity) * 1.25);
  mix-blend-mode: multiply;
}

.health-item > *,
.github-pill > *,
.theme-switch > * {
  position: relative;
  z-index: 1;
}

:global(.collector-app.dark .health-item::before),
:global(.collector-app.dark .github-pill::before),
:global(.collector-app.dark .theme-switch::before) {
  mix-blend-mode: screen;
}

.health-item:hover:not(:disabled) {
  border-color: rgba(9, 96, 189, 0.46);
  box-shadow: var(--paper-hover-shadow);
  transform: translateY(-1px);
}

.health-item:focus-visible {
  outline: 3px solid rgba(9, 96, 189, 0.22);
  outline-offset: 2px;
}

.health-item:disabled {
  cursor: wait;
}

.health-item--success {
  --health-state-color: #237a57;
}

.health-item--warning {
  --health-state-color: #8a6517;
}

.health-item--danger {
  --health-state-color: #b54745;
}

:global(.collector-app.dark .health-item) {
  --health-state-color: #c8d7ec;

  border-color: rgba(128, 153, 188, 0.22);
  background: var(--frost-bg-strong);
  box-shadow: var(--paper-shadow-sm);
}

:global(.collector-app.dark .health-item--success) {
  --health-state-color: #83c7a8;
}

:global(.collector-app.dark .health-item--warning) {
  --health-state-color: #d8b45f;
}

:global(.collector-app.dark .health-item--danger) {
  --health-state-color: #e08d88;
}

.health-icon,
.health-status-icon {
  flex: 0 0 auto;
  line-height: 1;
}

.health-icon {
  color: #15386f;
  font-size: 16px;
}

.health-status-icon {
  color: var(--health-state-color);
  font-size: 15px;
}

.health-item--checking .health-status-icon {
  animation: health-status-spin 980ms linear infinite;
}

@keyframes health-status-spin {
  to {
    transform: rotate(360deg);
  }
}

.health-label {
  flex: 0 0 auto;
  color: #15386f;
  font-size: 15px;
  font-weight: 500;
  line-height: 1;
  transform: translateY(1px);
}

.health-value {
  flex: 0 0 auto;
  min-width: max-content;
  overflow: visible;
  color: var(--health-state-color);
  font-size: 14px;
  font-weight: 400;
  line-height: 1;
  white-space: nowrap;
  text-overflow: clip;
  transform: translateY(1px);
}

:global(.collector-app.dark .health-icon),
:global(.collector-app.dark .health-label) {
  color: #d7e3f4;
}

@media (max-width: 1500px) {
  .topbar {
    gap: 16px;
    grid-template-columns: 470px minmax(0, 1fr);
  }

  .brand {
    margin-left: 28px;
  }

  .brand h1 {
    font-size: 32px;
  }

  .topbar-tools {
    gap: 12px;
    padding-right: 18px;
  }
}

.top-actions {
  display: contents;
}

.github-pill {
  position: relative;
  isolation: isolate;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  height: 48px;
  width: auto;
  min-width: max-content;
  padding: 0 12px;
  border: 1px solid rgba(104, 141, 181, 0.3);
  border-radius: 10px;
  color: var(--ink);
  background: var(--frost-bg-strong);
  box-shadow: var(--paper-shadow-sm);
  font-size: 15px;
  font-weight: 500;
  line-height: 1;
  text-decoration: none;
  overflow: hidden;
  transition:
    transform 160ms ease,
    color 160ms ease,
    background 160ms ease,
    border-color 160ms ease,
    box-shadow 160ms ease;
}

.github-pill:hover {
  transform: translateY(-1px);
  color: var(--blue);
  border-color: rgba(45, 111, 168, 0.42);
  background: var(--frost-bg-strong);
  box-shadow: var(--paper-hover-shadow);
}

.github-pill:active {
  transform: translateY(1px);
  box-shadow:
    inset 0 1px 2px rgba(35, 69, 111, 0.12),
    0 5px 10px rgba(35, 69, 111, 0.08);
}

.github-pill:focus-visible {
  outline: 2px solid rgba(45, 111, 168, 0.32);
  outline-offset: 3px;
}

.github-pill > .app-icon:first-child {
  font-size: 18px;
}

.github-open {
  color: rgba(45, 111, 168, 0.72);
  font-size: 12px;
}

.github-stars {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: #9f7a2d;
  font-size: 13px;
}

:global(.collector-app.dark .github-pill) {
  border-color: rgba(128, 153, 188, 0.22);
  color: #d7e3f4;
  background: var(--frost-bg-strong);
  box-shadow: var(--paper-shadow-sm);
}

:global(.collector-app.dark .github-pill:hover) {
  color: #9fc4f4;
  border-color: rgba(111, 154, 211, 0.34);
  background: var(--frost-bg-strong);
  box-shadow: var(--paper-hover-shadow);
}

.theme-switch {
  position: relative;
  isolation: isolate;
  display: grid;
  grid-template-columns: 1fr 1fr;
  align-items: center;
  width: 124px;
  height: 48px;
  padding: 3px;
  border: 1px solid rgba(104, 141, 181, 0.3);
  border-radius: 10px;
  color: var(--ink);
  background: var(--frost-bg-strong);
  box-shadow: var(--paper-shadow-sm);
  cursor: pointer;
  overflow: hidden;
}

.theme-switch span {
  display: grid;
  place-items: center;
  height: 40px;
  border-radius: 7px;
  font-size: 20px;
  line-height: 1;
  transition:
    color 160ms ease,
    background 160ms ease,
    box-shadow 160ms ease;
}

.theme-switch .sun {
  color: rgba(21, 56, 111, 0.62);
  background: #b7d8ff;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.46),
    0 3px 8px rgba(45, 117, 214, 0.16);
}

.theme-switch .moon {
  color: rgba(21, 56, 111, 0.62);
  background: transparent;
  box-shadow: none;
}

.theme-switch.is-dark .sun {
  background: transparent;
  color: rgba(199, 213, 232, 0.54);
  box-shadow: none;
}

.theme-switch.is-dark .moon {
  color: #dceaff;
  background: #275d9f;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.16),
    0 3px 7px rgba(0, 0, 0, 0.18);
}

:global(.collector-app.dark .theme-switch) {
  border-color: rgba(128, 153, 188, 0.22);
  background: var(--frost-bg-strong);
  box-shadow: var(--paper-shadow-sm);
}

@supports not ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
  .github-pill,
  .theme-switch {
    background: var(--paper);
  }
}

@media (prefers-reduced-transparency: reduce) {
  .github-pill,
  .theme-switch {
    background: var(--paper);
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .health-item--checking .health-status-icon {
    animation: none;
  }
}
</style>
