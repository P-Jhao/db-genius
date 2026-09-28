<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import MarkdownRenderer from '../common/MarkdownRenderer.vue'

const props = defineProps<{
  content: string
  streaming: boolean
  timestamp: number
}>()

const { locale } = useI18n()

const formattedTime = computed(() => {
  return new Date(props.timestamp).toLocaleTimeString(locale.value)
})
</script>

<template>
  <div class="summary-card">
    <div class="summary-header">
      <div class="summary-badge" :class="{ streaming }">
        <icon-check-circle v-if="!streaming" />
        <icon-loading v-else spin />
      </div>
      <span class="summary-label">{{ streaming ? $t('chat.summary.streaming') : $t('chat.summary.label') }}</span>
      <span class="summary-time">{{ formattedTime }}</span>
    </div>
    <div class="summary-body">
      <MarkdownRenderer :content="content" />
    </div>
  </div>
</template>

<style scoped lang="scss">
.summary-card {
  border: 1px solid #aff0b5;
  border-radius: 8px;
  background: #e8ffea;
  overflow: hidden;
  margin-top: 8px;
  animation: slideIn 0.3s ease;
}

.summary-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-bottom: 1px solid #aff0b5;
}

.summary-badge {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 6px;
  font-size: 14px;
  color: #00b42a;
  background: #d4f7d6;

  &.streaming {
    color: rgb(var(--primary-6));
    background: var(--color-fill-2);
  }
}

.summary-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--color-text-1);
}

.summary-time {
  margin-left: auto;
  font-size: 11px;
  color: var(--color-text-4);
}

.summary-body {
  padding: 12px;
  background: #fff;
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
