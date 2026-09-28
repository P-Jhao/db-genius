<script setup lang="ts">
import { ref, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    content: string
    streaming?: boolean
    done?: boolean
  }>(),
  {
    streaming: false,
    done: false,
  }
)

const collapsed = ref(false)
const userToggled = ref(false)

function toggle() {
  collapsed.value = !collapsed.value
  userToggled.value = true
}

// 思考结束后自动折叠，除非用户已手动操作过；immediate 使历史消息回放时默认折叠
watch(
  () => props.done,
  (done) => {
    if (done && !userToggled.value) {
      collapsed.value = true
    }
  },
  { immediate: true }
)
</script>

<template>
  <div class="reasoning-card">
    <div class="reasoning-header" @click="toggle">
      <div class="reasoning-badge">
        <icon-loading v-if="streaming" spin />
        <icon-bulb v-else />
      </div>
      <span class="reasoning-label">{{ streaming ? $t('chat.reasoning.thinking') : $t('chat.reasoning.label') }}</span>
      <icon-down class="reasoning-arrow" :class="{ collapsed }" />
    </div>
    <div v-show="!collapsed" class="reasoning-content">
      <pre>{{ content }}</pre>
    </div>
  </div>
</template>

<style scoped lang="scss">
.reasoning-card {
  border: 1px solid var(--color-border-1);
  border-radius: 8px;
  overflow: hidden;
  margin-bottom: 8px;
  background: #f7f8fa;
  animation: slideIn 0.3s ease;
}

.reasoning-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  cursor: pointer;
  user-select: none;
}

.reasoning-badge {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 6px;
  font-size: 14px;
  color: #86909c;
  background: #e5e6eb;
}

.reasoning-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--color-text-2);
}

.reasoning-arrow {
  margin-left: auto;
  font-size: 12px;
  color: var(--color-text-3);
  transition: transform 0.2s ease;

  &.collapsed {
    transform: rotate(-90deg);
  }
}

.reasoning-content {
  padding: 8px 12px;
  border-top: 1px solid var(--color-border-1);
  max-height: 320px;
  overflow-y: auto;

  pre {
    white-space: pre-wrap;
    word-break: break-word;
    font-size: 13px;
    line-height: 1.6;
    font-family: inherit;
    color: var(--color-text-3);
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
