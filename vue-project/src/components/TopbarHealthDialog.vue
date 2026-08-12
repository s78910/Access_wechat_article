<script setup lang="ts">
import AppIcon from './AppIcon.vue'
import type { HealthCheckItem } from '../bridge/pythonApi'

type HealthDialogTone = 'success' | 'warning' | 'danger' | 'info'

const props = withDefaults(defineProps<{
  visible: boolean
  title: string
  icon: string
  tone: HealthDialogTone
  statusLabel: string
  message: string
  items: HealthCheckItem[]
  checkedAt?: string
  checking?: boolean
}>(), {
  checkedAt: '',
  checking: false,
})

const emit = defineEmits<{
  close: []
}>()

function itemValue(item: HealthCheckItem) {
  return item.pathAbsolute || item.value || item.message || '暂无结果'
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="props.visible"
      class="health-dialog-backdrop"
      @click.self="emit('close')"
    >
      <section
        class="health-dialog"
        :class="`health-dialog--${props.tone}`"
        role="dialog"
        aria-modal="true"
        aria-labelledby="health-dialog-title"
        :aria-busy="props.checking"
      >
        <header class="health-dialog-header">
          <span class="health-dialog-main-icon" aria-hidden="true">
            <AppIcon :icon="props.icon" />
          </span>
          <div class="health-dialog-heading">
            <h2 id="health-dialog-title">{{ props.title }}</h2>
            <span class="health-dialog-status">
              <AppIcon
                :icon="props.checking ? 'fa-solid fa-rotate' : props.tone === 'success' ? 'fa-solid fa-circle-check' : 'fa-solid fa-triangle-exclamation'"
                aria-hidden="true"
              />
              {{ props.checking ? '正在检测' : props.statusLabel }}
            </span>
          </div>
          <button class="health-dialog-close" type="button" aria-label="关闭检测结果" @click="emit('close')">
            <AppIcon icon="fa-solid fa-xmark" />
          </button>
        </header>

        <p class="health-dialog-message">{{ props.message || '正在检测，请稍候...' }}</p>

        <div v-if="props.items.length" class="health-dialog-results" aria-live="polite">
          <div
            v-for="item in props.items"
            :key="item.key"
            class="health-result-row"
          >
            <AppIcon
              class="health-result-icon"
              :icon="item.ok === false ? 'fa-solid fa-triangle-exclamation' : 'fa-solid fa-circle-check'"
              aria-hidden="true"
            />
            <dt>{{ item.label }}</dt>
            <dd>
              <strong>{{ itemValue(item) }}</strong>
              <small v-if="item.message">{{ item.message }}</small>
              <small v-if="item.action">{{ item.action }}</small>
            </dd>
          </div>
        </div>

        <div v-else class="health-dialog-pending" aria-live="polite">
          <AppIcon icon="fa-solid fa-rotate" aria-hidden="true" />
          <span>正在检测并读取最新状态...</span>
        </div>

        <footer v-if="props.checkedAt && !props.checking" class="health-dialog-footer">
          检测时间：{{ props.checkedAt.replace('T', ' ') }}
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.health-dialog-backdrop {
  position: fixed;
  inset: 0;
  z-index: 1200;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgba(18, 34, 55, 0.38);
  backdrop-filter: blur(4px);
}

.health-dialog {
  --health-dialog-color: #285d91;
  --health-dialog-soft: #edf5fd;

  width: min(680px, calc(100vw - 32px));
  max-height: min(720px, calc(100vh - 48px));
  overflow: auto;
  border: 1px solid rgba(95, 129, 166, 0.34);
  border-radius: 8px;
  color: #20354f;
  background: #f9fcff;
  box-shadow: 0 22px 60px rgba(19, 45, 77, 0.24);
}

.health-dialog--success {
  --health-dialog-color: #237a57;
  --health-dialog-soft: #e8f6ef;
}

.health-dialog--warning {
  --health-dialog-color: #8a6517;
  --health-dialog-soft: #fff7df;
}

.health-dialog--danger {
  --health-dialog-color: #b54745;
  --health-dialog-soft: #fff0ef;
}

.health-dialog-header {
  display: grid;
  grid-template-columns: 46px minmax(0, 1fr) 36px;
  gap: 12px;
  align-items: center;
  padding: 20px 22px 16px;
  border-bottom: 1px solid rgba(104, 141, 181, 0.22);
}

.health-dialog-main-icon {
  display: grid;
  place-items: center;
  width: 46px;
  height: 46px;
  border-radius: 8px;
  color: var(--health-dialog-color);
  background: var(--health-dialog-soft);
  font-size: 21px;
}

.health-dialog-heading {
  display: flex;
  min-width: 0;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.health-dialog-heading h2 {
  margin: 0;
  font-size: 19px;
  line-height: 1.35;
  letter-spacing: 0;
}

.health-dialog-status {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 7px;
  color: var(--health-dialog-color);
  font-size: 14px;
  font-weight: 800;
}

.health-dialog--warning .health-dialog-status .app-icon,
.health-dialog-pending .app-icon {
  animation: health-dialog-spin 980ms linear infinite;
}

.health-dialog-close {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  padding: 0;
  border: 0;
  border-radius: 6px;
  color: #5a6f87;
  background: transparent;
  cursor: pointer;
}

.health-dialog-close:hover,
.health-dialog-close:focus-visible {
  color: #15386f;
  background: #eaf2fb;
  outline: none;
}

.health-dialog-message {
  margin: 0;
  padding: 16px 22px;
  color: #50657e;
  font-size: 14px;
  line-height: 1.7;
}

.health-dialog-results {
  margin: 0 22px 20px;
  overflow: hidden;
  border: 1px solid rgba(104, 141, 181, 0.24);
  border-radius: 8px;
  background: #fff;
}

.health-result-row {
  display: grid;
  grid-template-columns: 20px 112px minmax(0, 1fr);
  gap: 10px;
  align-items: start;
  padding: 12px 14px;
}

.health-result-row + .health-result-row {
  border-top: 1px solid rgba(104, 141, 181, 0.18);
}

.health-result-icon {
  margin-top: 3px;
  color: var(--health-dialog-color);
  font-size: 13px;
}

.health-result-row dt,
.health-result-row dd {
  margin: 0;
  min-width: 0;
}

.health-result-row dt {
  color: #62778f;
  font-size: 13px;
  font-weight: 700;
  line-height: 1.55;
}

.health-result-row dd {
  display: grid;
  gap: 3px;
}

.health-result-row strong {
  overflow-wrap: anywhere;
  color: #20354f;
  font-size: 13px;
  line-height: 1.55;
  letter-spacing: 0;
}

.health-result-row small {
  color: #71849a;
  font-size: 12px;
  line-height: 1.5;
}

.health-dialog-pending {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  min-height: 116px;
  margin: 0 22px 20px;
  border: 1px dashed rgba(138, 101, 23, 0.38);
  border-radius: 8px;
  color: #765919;
  background: #fffaf0;
  font-size: 14px;
  font-weight: 700;
}

.health-dialog-footer {
  padding: 0 22px 18px;
  color: #7b8da1;
  font-size: 12px;
  text-align: right;
}

:global(.collector-app.dark) + .health-dialog-backdrop .health-dialog,
:global(body:has(.collector-app.dark)) .health-dialog {
  color: #d9e5f4;
  border-color: rgba(128, 153, 188, 0.26);
  background: #17243a;
  box-shadow: 0 22px 60px rgba(0, 0, 0, 0.46);
}

:global(body:has(.collector-app.dark)) .health-dialog-header,
:global(body:has(.collector-app.dark)) .health-result-row + .health-result-row {
  border-color: rgba(128, 153, 188, 0.2);
}

:global(body:has(.collector-app.dark)) .health-dialog-results {
  border-color: rgba(128, 153, 188, 0.22);
  background: #1d2c44;
}

:global(body:has(.collector-app.dark)) .health-dialog-heading h2,
:global(body:has(.collector-app.dark)) .health-result-row strong {
  color: #e2ebf7;
}

:global(body:has(.collector-app.dark)) .health-dialog-message,
:global(body:has(.collector-app.dark)) .health-result-row dt,
:global(body:has(.collector-app.dark)) .health-result-row small,
:global(body:has(.collector-app.dark)) .health-dialog-footer {
  color: #aebed2;
}

:global(body:has(.collector-app.dark)) .health-dialog-pending {
  border-color: rgba(216, 180, 95, 0.34);
  color: #e1c577;
  background: #2a2a29;
}

@keyframes health-dialog-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 640px) {
  .health-dialog-backdrop {
    padding: 16px;
  }

  .health-dialog-header {
    grid-template-columns: 42px minmax(0, 1fr) 34px;
    padding: 16px;
  }

  .health-dialog-heading {
    display: grid;
    gap: 4px;
  }

  .health-dialog-message {
    padding: 14px 16px;
  }

  .health-dialog-results,
  .health-dialog-pending {
    margin-right: 16px;
    margin-left: 16px;
  }

  .health-result-row {
    grid-template-columns: 18px minmax(0, 1fr);
  }

  .health-result-row dd {
    grid-column: 2;
  }
}

@media (prefers-reduced-motion: reduce) {
  .health-dialog--warning .health-dialog-status .app-icon,
  .health-dialog-pending .app-icon {
    animation: none;
  }
}
</style>
