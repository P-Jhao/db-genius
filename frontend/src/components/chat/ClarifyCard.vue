<script setup lang="ts">
import type { ClarifyContent, IntentType } from '../../types'

const props = defineProps<{
  content: ClarifyContent
}>()

const emit = defineEmits<{
  confirm: [intent: IntentType]
}>()

function handleSelect(intent: IntentType) {
  emit('confirm', intent)
}
</script>

<template>
  <div class="clarify-card">
    <div class="clarify-question">{{ props.content.question }}</div>
    <div v-if="props.content.reasoning" class="clarify-reasoning">{{ props.content.reasoning }}</div>
    <div class="clarify-options">
      <a-button
        v-for="opt in props.content.options"
        :key="opt.intent"
        type="outline"
        size="small"
        @click="handleSelect(opt.intent)"
      >
        {{ opt.label }}
      </a-button>
    </div>
  </div>
</template>

<style scoped lang="scss">
.clarify-card {
  border: 1px solid var(--color-border-1);
  border-radius: 8px;
  padding: 12px;
  background: #fff;
  animation: slideIn 0.3s ease;
}

.clarify-question {
  font-size: 14px;
  font-weight: 500;
  color: var(--color-text-1);
  margin-bottom: 8px;
}

.clarify-reasoning {
  font-size: 12px;
  color: var(--color-text-3);
  margin-bottom: 12px;
  line-height: 1.5;
}

.clarify-options {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
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
