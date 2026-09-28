<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { Message, Modal } from '@arco-design/web-vue'
import { useI18n } from 'vue-i18n'
import { useChatStore } from '../../stores/chat'
import { compressConversation } from '../../api/chat'
import { getActiveModelConfig } from '../../api/modelConfig'

const { t } = useI18n()
const chatStore = useChatStore()
const compressing = ref(false)

// 占用百分比；模型窗口未知时为 null（只显示绝对值）
const percent = computed(() => {
  if (!chatStore.contextWindow) return null
  return Math.min(100, (chatStore.contextTokens / chatStore.contextWindow) * 100)
})

const overThreshold = computed(() => percent.value != null && percent.value >= 80)

const progressStatus = computed<'normal' | 'warning' | 'danger'>(() => {
  if (percent.value == null) return 'normal'
  if (percent.value >= 95) return 'danger'
  if (percent.value >= 80) return 'warning'
  return 'normal'
})

function fmt(n: number) {
  return n.toLocaleString()
}

// 首条消息发出前预置窗口分母（来自当前生效的模型配置）
onMounted(async () => {
  if (chatStore.contextWindow == null) {
    try {
      const res = await getActiveModelConfig()
      chatStore.contextWindow = res.data.contextWindow ?? null
    } catch {
      // 获取失败不阻塞，usage 事件会再次带回 contextWindow
    }
  }
})

// 首次越过 80% 阈值弹窗提示（warnedAt80 由 store 在占用回落时复位）
watch(overThreshold, (over) => {
  if (over && !chatStore.warnedAt80) {
    chatStore.warnedAt80 = true
    Modal.warning({
      title: t('chat.context.modalTitle'),
      content: t('chat.context.modalContent', { percent: percent.value?.toFixed(1) }),
      okText: t('chat.context.modalOk'),
    })
  }
})

async function handleCompress() {
  if (!chatStore.currentConversationId) {
    Message.info(t('chat.context.needConversation'))
    return
  }
  compressing.value = true
  try {
    const res = await compressConversation(chatStore.currentConversationId)
    Message.info(res.data.message || t('chat.context.compressDone'))
    if (res.data.afterTokens != null) {
      chatStore.contextTokens = res.data.afterTokens
    }
  } catch {
    Message.error(t('chat.context.compressFailed'))
  } finally {
    compressing.value = false
  }
}
</script>

<template>
  <div class="context-usage-bar">
    <div class="usage-row">
      <template v-if="chatStore.contextWindow">
        <span class="usage-text">
          {{ $t('chat.context.usage', { used: fmt(chatStore.contextTokens), total: fmt(chatStore.contextWindow) }) }}
          <template v-if="percent != null">({{ percent.toFixed(1) }}%)</template>
        </span>
        <a-progress
          class="usage-progress"
          size="small"
          :percent="(percent ?? 0) / 100"
          :status="progressStatus"
          :show-text="false"
        />
      </template>
      <template v-else>
        <a-tooltip :content="$t('chat.context.windowUnknownTip')">
          <span class="usage-text usage-text--unknown">
            {{ $t('chat.context.unknownUsage', { tokens: chatStore.contextTokens > 0 ? fmt(chatStore.contextTokens) : '—' }) }}
          </span>
        </a-tooltip>
      </template>
      <span v-if="chatStore.conversationTotalTokens > 0" class="usage-total">
        {{ $t('chat.context.totalTokens', { count: fmt(chatStore.conversationTotalTokens) }) }}
      </span>
    </div>

    <a-alert
      v-if="overThreshold"
      type="warning"
      class="compress-alert"
      :title="$t('chat.context.overThresholdTip')"
    >
      <template #action>
        <a-button size="mini" type="primary" :loading="compressing" @click="handleCompress">
          {{ $t('chat.context.compress') }}
        </a-button>
      </template>
    </a-alert>
  </div>
</template>

<style scoped lang="scss">
.context-usage-bar {
  margin-bottom: 10px;
}

.usage-row {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  color: var(--color-text-3);
}

.usage-text {
  flex-shrink: 0;

  &--unknown {
    cursor: help;
    border-bottom: 1px dashed var(--color-border-2);
  }
}

.usage-progress {
  flex: 1;
  min-width: 80px;
  max-width: 320px;
}

.usage-total {
  margin-left: auto;
  flex-shrink: 0;
}

.compress-alert {
  margin-top: 8px;
}
</style>
