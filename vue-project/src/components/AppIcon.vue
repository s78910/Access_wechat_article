<script setup lang="ts">
import { computed, useAttrs } from 'vue'
import { fontAwesomeIcons } from '../icons/fontAwesomeIcons'

const props = defineProps<{
  icon: unknown
}>()

defineOptions({
  inheritAttrs: false,
})

const attrs = useAttrs()

const STYLE_CLASS_PATTERN = /^fa-(solid|regular|brands)$/
const ICON_CLASS_PATTERN = /^fa-[\w-]+$/

function flattenClassInput(value: unknown): string[] {
  if (!value) {
    return []
  }

  if (typeof value === 'string') {
    return value.split(/\s+/).filter(Boolean)
  }

  if (Array.isArray(value)) {
    return value.flatMap((item) => flattenClassInput(item))
  }

  if (typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>)
      .filter(([, enabled]) => Boolean(enabled))
      .flatMap(([className]) => flattenClassInput(className))
  }

  return []
}

const iconClasses = computed(() => flattenClassInput(props.icon))

const iconKey = computed(() => {
  const styleClass = iconClasses.value.find((className) => STYLE_CLASS_PATTERN.test(className))
  const iconClass = iconClasses.value.find(
    (className) => ICON_CLASS_PATTERN.test(className) && !STYLE_CLASS_PATTERN.test(className),
  )

  return styleClass && iconClass ? `${styleClass} ${iconClass}` : ''
})

const displayClasses = computed(() =>
  iconClasses.value.filter((className) => !className.startsWith('fa-') && className !== 'fa'),
)

const componentClass = computed(() => ['app-icon', displayClasses.value, attrs.class])

const forwardedAttrs = computed(() => {
  const { class: _class, ...restAttrs } = attrs
  return restAttrs
})

const definition = computed(() => fontAwesomeIcons[iconKey.value as keyof typeof fontAwesomeIcons])
</script>

<template>
  <svg
    v-if="definition"
    v-bind="forwardedAttrs"
    :class="componentClass"
    :viewBox="definition.viewBox"
    aria-hidden="true"
    focusable="false"
  >
    <path v-for="path in definition.paths" :key="path" fill="currentColor" :d="path" />
  </svg>
  <span
    v-else
    v-bind="forwardedAttrs"
    :class="[componentClass, 'app-icon-missing']"
    aria-hidden="true"
  ></span>
</template>

<style scoped>
.app-icon {
  display: inline-block;
  width: 1em;
  height: 1em;
  flex: 0 0 auto;
  color: currentColor;
  line-height: 1;
  vertical-align: -0.125em;
}

.app-icon-missing {
  border-radius: 50%;
  background: currentColor;
  opacity: 0.25;
}
</style>
