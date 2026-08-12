<script setup lang="ts">
import AppIcon from './AppIcon.vue'

type ConfirmTone = 'info' | 'warning' | 'danger' | 'success'

type ConfirmSummaryItem = {
  label: string
  value: string
}

const props = withDefaults(defineProps<{
  open: boolean
  title: string
  description: string
  summaryItems: ConfirmSummaryItem[]
  detailTitle?: string
  detailItems?: string[]
  warning?: string
  errorMessage?: string
  loading?: boolean
  tone?: ConfirmTone
  icon?: string
  confirmIcon?: string
  confirmText?: string
  cancelText?: string
  loadingText?: string
}>(), {
  tone: 'info',
  icon: '',
  confirmIcon: '',
  confirmText: '确认',
  cancelText: '取消',
  loadingText: '处理中...',
  warning: '',
  errorMessage: '',
})

defineEmits<{
  cancel: []
  confirm: []
}>()

function resolveIcon() {
  if (props.icon) {
    return props.icon
  }

  if (props.tone === 'danger') {
    return 'fa-solid fa-triangle-exclamation'
  }

  if (props.tone === 'warning') {
    return 'fa-solid fa-circle-exclamation'
  }

  if (props.tone === 'success') {
    return 'fa-solid fa-check'
  }

  return 'fa-solid fa-circle-info'
}
</script>

<template>
  <Teleport to="body">
    <transition name="confirm-dialog-fade">
      <div v-if="open" class="confirm-dialog-layer" role="presentation">
        <section
          :class="['confirm-dialog', `tone-${tone}`]"
          role="dialog"
          aria-modal="true"
          aria-labelledby="confirm-dialog-title"
          aria-describedby="confirm-dialog-description"
        >
          <header class="confirm-dialog-head">
            <span class="confirm-dialog-icon" aria-hidden="true">
              <AppIcon :icon="resolveIcon()" />
            </span>
            <div>
              <h2 id="confirm-dialog-title">{{ title }}</h2>
              <p id="confirm-dialog-description">{{ description }}</p>
            </div>
          </header>

          <dl v-if="summaryItems.length" class="confirm-summary">
            <div v-for="item in summaryItems" :key="item.label" class="confirm-summary-item">
              <dt>{{ item.label }}</dt>
              <dd>{{ item.value }}</dd>
            </div>
          </dl>

          <div v-if="detailItems?.length" class="confirm-detail">
            <strong>{{ detailTitle || '明细预览' }}</strong>
            <ul>
              <li v-for="item in detailItems" :key="item">{{ item }}</li>
            </ul>
          </div>

          <p v-if="warning" class="confirm-warning">
            <AppIcon icon="fa-solid fa-triangle-exclamation" />
            <span>{{ warning }}</span>
          </p>

          <p v-if="errorMessage" class="confirm-error" role="alert">{{ errorMessage }}</p>

          <footer class="confirm-dialog-actions">
            <button class="action-button ghost" type="button" :disabled="loading" @click="$emit('cancel')">
              {{ cancelText }}
            </button>
            <button :class="['action-button', tone]" type="button" :disabled="loading" @click="$emit('confirm')">
              <AppIcon v-if="confirmIcon" :icon="confirmIcon" />
              {{ loading ? loadingText : confirmText }}
            </button>
          </footer>
        </section>
      </div>
    </transition>
  </Teleport>
</template>

<style scoped>
.confirm-dialog-layer {
  position: fixed;
  inset: 0;
  z-index: 4200;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgba(12, 31, 58, 0.38);
}

.confirm-dialog {
  width: min(560px, 100%);
  max-height: min(720px, calc(100vh - 48px));
  overflow: auto;
  border: 1px solid rgba(104, 141, 181, 0.34);
  border-radius: 10px;
  color: var(--ink);
  background:
    linear-gradient(135deg, rgba(255, 255, 255, 0.82), transparent 44%),
    linear-gradient(180deg, rgba(251, 253, 255, 0.98), rgba(242, 248, 252, 0.96));
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.86),
    0 18px 34px rgba(24, 49, 85, 0.22);
  padding: 18px 20px;
}

.confirm-dialog-head {
  display: grid;
  grid-template-columns: 42px minmax(0, 1fr);
  gap: 12px;
  align-items: start;
}

.confirm-dialog-icon {
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  border: 1px solid rgba(45, 117, 214, 0.28);
  border-radius: 10px;
  color: var(--blue);
  background: rgba(45, 117, 214, 0.1);
  font-size: 17px;
}

.confirm-dialog.tone-warning .confirm-dialog-icon {
  color: #8a3a12;
  border-color: rgba(223, 122, 53, 0.3);
  background: rgba(223, 122, 53, 0.12);
}

.confirm-dialog.tone-danger .confirm-dialog-icon {
  color: #c93e3a;
  border-color: rgba(217, 65, 63, 0.32);
  background: rgba(217, 65, 63, 0.1);
}

.confirm-dialog.tone-success .confirm-dialog-icon {
  color: var(--green);
  border-color: rgba(31, 143, 105, 0.3);
  background: rgba(31, 143, 105, 0.12);
}

.confirm-dialog h2 {
  margin: 0;
  color: var(--ink-strong);
  font-size: 18px;
  font-weight: 900;
  line-height: 1.25;
}

.confirm-dialog p {
  margin: 0;
}

.confirm-dialog-head p {
  margin-top: 6px;
  color: var(--ink);
  font-size: 13px;
  font-weight: 800;
  line-height: 1.55;
}

.confirm-summary {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin: 16px 0 0;
}

.confirm-summary-item {
  min-width: 0;
  border: 1px solid rgba(104, 141, 181, 0.22);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.56);
  padding: 10px 12px;
}

.confirm-summary dt {
  margin: 0;
  color: var(--ink-muted);
  font-size: 12px;
  font-weight: 900;
}

.confirm-summary dd {
  overflow: hidden;
  margin: 5px 0 0;
  color: var(--ink-strong);
  font-size: 14px;
  font-weight: 900;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.confirm-detail {
  margin-top: 14px;
  border: 1px solid rgba(104, 141, 181, 0.22);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.44);
  padding: 11px 12px;
}

.confirm-detail strong {
  display: block;
  color: var(--ink-strong);
  font-size: 13px;
  font-weight: 900;
}

.confirm-detail ul {
  display: grid;
  gap: 6px;
  margin: 8px 0 0;
  padding: 0;
  list-style: none;
}

.confirm-detail li {
  overflow: hidden;
  color: var(--ink);
  font-size: 13px;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.confirm-warning {
  display: grid;
  grid-template-columns: 18px minmax(0, 1fr);
  gap: 8px;
  align-items: start;
  margin-top: 14px;
  color: #8a3a12;
  background: rgba(223, 122, 53, 0.13);
  border: 1px solid rgba(223, 122, 53, 0.24);
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 13px;
  font-weight: 900;
  line-height: 1.55;
}

.confirm-warning :deep(.app-icon) {
  margin-top: 2px;
}

.confirm-error {
  margin-top: 10px;
  color: #b8322f;
  background: rgba(217, 65, 63, 0.1);
  border: 1px solid rgba(217, 65, 63, 0.22);
  border-radius: 8px;
  padding: 9px 12px;
  font-size: 13px;
  font-weight: 900;
}

.confirm-dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 16px;
}

.confirm-dialog-actions .action-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-width: 96px;
  height: 38px;
  border: 1px solid rgba(104, 141, 181, 0.34);
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 900;
}

.confirm-dialog-actions .action-button.ghost {
  color: var(--blue);
  background: rgba(255, 255, 255, 0.42);
}

.confirm-dialog-actions .action-button.info {
  color: #ffffff;
  border-color: rgba(45, 117, 214, 0.46);
  background: linear-gradient(135deg, #4d8edf, #2d75d6);
}

.confirm-dialog-actions .action-button.warning {
  color: #ffffff;
  border-color: rgba(223, 122, 53, 0.44);
  background: linear-gradient(135deg, #ee9d55, #df7a35);
}

.confirm-dialog-actions .action-button.danger {
  color: #ffffff;
  border-color: rgba(217, 65, 63, 0.44);
  background: linear-gradient(135deg, #e4635f, #c93e3a);
}

.confirm-dialog-actions .action-button.success {
  color: #ffffff;
  border-color: rgba(31, 143, 105, 0.44);
  background: linear-gradient(135deg, #3fa77f, #1f8f69);
}

.confirm-dialog-actions .action-button:disabled {
  cursor: not-allowed;
  opacity: 0.58;
}

.confirm-dialog-fade-enter-active,
.confirm-dialog-fade-leave-active {
  transition: opacity 160ms ease;
}

.confirm-dialog-fade-enter-active .confirm-dialog,
.confirm-dialog-fade-leave-active .confirm-dialog {
  transition: transform 160ms ease;
}

.confirm-dialog-fade-enter-from,
.confirm-dialog-fade-leave-to {
  opacity: 0;
}

.confirm-dialog-fade-enter-from .confirm-dialog,
.confirm-dialog-fade-leave-to .confirm-dialog {
  transform: translateY(8px);
}

@media (max-width: 640px) {
  .confirm-summary {
    grid-template-columns: 1fr;
  }
}

@media (prefers-reduced-transparency: reduce) {
  .confirm-dialog-layer {
    background: rgba(12, 31, 58, 0.48);
  }

  .confirm-dialog {
    background: #fbfdff;
  }
}

@media (prefers-reduced-motion: reduce) {
  .confirm-dialog-fade-enter-active,
  .confirm-dialog-fade-leave-active,
  .confirm-dialog-fade-enter-active .confirm-dialog,
  .confirm-dialog-fade-leave-active .confirm-dialog {
    transition: opacity 80ms ease;
  }

  .confirm-dialog-fade-enter-from .confirm-dialog,
  .confirm-dialog-fade-leave-to .confirm-dialog {
    transform: none;
  }
}
</style>
