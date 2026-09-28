<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { SseEvent } from '../../types'

withDefaults(
  defineProps<{
    event: SseEvent
    isActive?: boolean
  }>(),
  {
    isActive: false,
  }
)

const { t, locale } = useI18n()

const displayContent = computed(() => (event: SseEvent) => {
  if (event.type === 'classified' && event.content && typeof event.content === 'object') {
    return JSON.stringify(event.content, null, 2)
  }
  return (event.content as string) || ''
})

const stepLabel = computed(() => (event: SseEvent) => {
  switch (event.type) {
    case 'classifying':
      return t('chat.steps.classifying')
    case 'classified':
      return t('chat.steps.classified')
    case 'clarify':
      return t('chat.steps.clarify')
    case 'routing':
      return t('chat.steps.routing')
    case 'thinking':
      return t('chat.steps.thinking')
    case 'step':
      return t('chat.steps.step', { n: event.step })
    case 'content':
      return t('chat.steps.content')
    case 'error':
      return t('chat.steps.error')
    default:
      return event.type
  }
})

const stepTime = computed(() => (event: SseEvent) => {
  return new Date(event.timestamp).toLocaleTimeString(locale.value)
})
</script>

<template>
  <div class="step-card" :class="[event.type]">
    <div class="step-header">
      <div class="step-badge" :class="event.type">
        <icon-loading v-if="(event.type === 'thinking' || event.type === 'classifying') && isActive" spin />
        <icon-robot v-else-if="event.type === 'thinking' || event.type === 'classifying'" />
        <icon-check-circle v-else-if="event.type === 'classified'" />
        <icon-message v-else-if="event.type === 'content' || event.type === 'clarify'" />
        <icon-thunderbolt v-else-if="event.type === 'routing' || event.type === 'step'" />
        <icon-close-circle v-else-if="event.type === 'error'" />
      </div>
      <span class="step-label">{{ stepLabel(event) }}</span>
      <span class="step-time">{{ stepTime(event) }}</span>
    </div>
    <div class="step-content">
      <pre>{{ displayContent(event) }}</pre>
    </div>
  </div>
</template>

<style scoped lang="scss">
.step-card {
  border: 1px solid var(--color-border-1);
  border-radius: 8px;
  overflow: hidden;
  margin-bottom: 8px;
  animation: slideIn 0.3s ease;

  &.thinking,
  &.classifying {
    border-color: #bdd9fc;
    background: #f2f9ff;
    .step-badge { color: #165DFF; background: #e8f3ff; }
  }

  &.classified {
    border-color: #aff0b5;
    background: #e8ffea;
    .step-badge { color: #00B42A; background: #d4f7d6; }
  }

  &.clarify,
  &.content {
    border-color: #e5e6eb;
    background: #fafafa;
    .step-badge { color: #722ED1; background: #f5e8ff; }
  }

  &.routing {
    border-color: #e5e6eb;
    background: #fff;
    .step-badge { color: #F7BA1E; background: #fff7e8; }
  }

  &.step {
    border-color: #e5e6eb;
    background: #fafafa;
    .step-badge { color: #722ED1; background: #f5e8ff; }
  }

  &.summary {
    border-color: #aff0b5;
    background: #e8ffea;
    .step-badge { color: #00B42A; background: #d4f7d6; }
  }

  &.error {
    border-color: #fdcdc5;
    background: #fff2f0;
    .step-badge { color: #F53F3F; background: #ffece8; }
  }
}

.step-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--color-border-1);
}

.step-badge {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 6px;
  font-size: 14px;
}

.step-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--color-text-1);
}

.step-time {
  margin-left: auto;
  font-size: 11px;
  color: var(--color-text-4);
}

.step-content {
  padding: 8px 12px;

  pre {
    white-space: pre-wrap;
    word-break: break-word;
    font-size: 13px;
    line-height: 1.6;
    font-family: 'SF Mono', Monaco, Menlo, Consolas, monospace;
    color: var(--color-text-2);
    margin: 0;
  }
}

@keyframes slideIn {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
