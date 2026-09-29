<script setup lang="ts">
import { computed } from 'vue'
import type { ClarifyContent, SseEvent } from '../../types'
import type { ChatMessage, ChatBlock } from '../../stores/chat'
import SseStepCard from './SseStepCard.vue'
import SummaryCard from './SummaryCard.vue'
import ClarifyCard from './ClarifyCard.vue'
import ReasoningCard from './ReasoningCard.vue'
import MarkdownRenderer from '../common/MarkdownRenderer.vue'

const props = defineProps<{
  message: ChatMessage
}>()

const emit = defineEmits<{
  confirmIntent: [intent: string]
}>()

const eventBlocks = computed(() =>
  props.message.blocks.filter((b): b is Extract<ChatBlock, { kind: 'event' }> => b.kind === 'event')
)
const hasSummary = computed(() => props.message.blocks.some((b) => b.kind === 'summary'))
const hasContent = computed(() => props.message.content && !hasSummary.value)
const lastEventIndex = computed(() => eventBlocks.value.length - 1)

function isClarifyContent(content: SseEvent['content']): content is ClarifyContent {
  return content !== null && typeof content === 'object' && 'question' in content && 'options' in content && 'reasoning' in content
}

function eventIndex(block: ChatBlock): number {
  return eventBlocks.value.indexOf(block as Extract<ChatBlock, { kind: 'event' }>)
}

function handleConfirm(intent: string) {
  emit('confirmIntent', intent)
}
</script>

<template>
  <div class="message-bubble" :class="message.role">
    <div class="bubble-avatar">
      <a-avatar v-if="message.role === 'user'" :size="32" :style="{ backgroundColor: '#165DFF' }">
        <icon-user />
      </a-avatar>
      <a-avatar v-else :size="32" :style="{ backgroundColor: '#0FC6C2' }">
        <icon-robot />
      </a-avatar>
    </div>
    <div class="bubble-body">
      <div class="bubble-role">{{ message.role === 'user' ? $t('chat.message.me') : $t('chat.message.assistant') }}</div>

      <div v-if="message.role === 'user'" class="bubble-content">
        <p>{{ message.content }}</p>
      </div>

      <div v-else class="bubble-content assistant-content">
        <div v-if="message.blocks.length > 0" class="blocks-timeline">
          <template v-for="(block, idx) in message.blocks" :key="idx">
            <ReasoningCard
              v-if="block.kind === 'reasoning'"
              :content="block.text"
              :streaming="message.streaming && !block.done"
              :done="block.done || !message.streaming"
            />
            <SummaryCard
              v-else-if="block.kind === 'summary'"
              :content="block.text"
              :streaming="message.streaming && !block.done"
              :timestamp="block.timestamp"
            />
            <ClarifyCard
              v-else-if="block.event.type === 'clarify' && isClarifyContent(block.event.content)"
              :content="block.event.content"
              @confirm="handleConfirm"
            />
            <SseStepCard
              v-else
              :event="block.event"
              :is-active="message.streaming && eventIndex(block) === lastEventIndex"
            />
          </template>
        </div>

        <div v-if="hasContent" class="assistant-text">
          <MarkdownRenderer :content="message.content" />
        </div>

        <div v-if="message.streaming && !hasSummary && !message.content" class="streaming-indicator">
          <span class="loading-dots"><span /><span /><span /></span>
          <span>{{ $t('chat.message.processing') }}</span>
        </div>

        <div v-if="!message.streaming && message.usage" class="usage-line">
          {{ $t('chat.message.usageLine', {
            total: message.usage.totalTokens.toLocaleString(),
            prompt: message.usage.promptTokens.toLocaleString(),
            completion: message.usage.completionTokens.toLocaleString(),
            count: message.usage.callCount,
          }) }}
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.message-bubble {
  display: flex;
  gap: 12px;
  padding: 12px 0;

  &.user {
    flex-direction: row-reverse;

    .bubble-body {
      align-items: flex-end;
    }

    .bubble-content {
      background: #e8f3ff;
      border-radius: 16px 4px 16px 16px;
    }

    .bubble-role {
      text-align: right;
    }
  }

  &.assistant {
    .bubble-content {
      background: #fff;
      border: 1px solid var(--color-border-1);
      border-radius: 4px 16px 16px 16px;
    }
  }
}

.bubble-body {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  max-width: 75%;
}

.bubble-role {
  font-size: 12px;
  color: var(--color-text-3);
  padding: 0 4px;
}

.bubble-content {
  padding: 12px 16px;

  p {
    font-size: 14px;
    line-height: 1.6;
    color: var(--color-text-1);
    margin: 0;
    white-space: pre-wrap;
  }
}

.assistant-content {
  min-width: 300px;
}

.assistant-text {
  margin-top: 8px;
  font-size: 14px;
  line-height: 1.6;
  color: var(--color-text-1);
}

.blocks-timeline {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.streaming-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
  padding: 4px 0;
  font-size: 13px;
  color: var(--color-text-3);
}

.usage-line {
  margin-top: 8px;
  font-size: 12px;
  color: var(--color-text-4);
}

.loading-dots {
  display: inline-flex;
  gap: 3px;

  span {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: rgb(var(--primary-6));
    animation: dotPulse 1.4s ease-in-out infinite;

    &:nth-child(2) { animation-delay: 0.2s; }
    &:nth-child(3) { animation-delay: 0.4s; }
  }
}

@keyframes dotPulse {
  0%, 80%, 100% { opacity: 0.3; transform: scale(0.8); }
  40% { opacity: 1; transform: scale(1); }
}

@media (max-width: 768px) {
  .bubble-body {
    max-width: 85%;
  }

  .assistant-content {
    min-width: 240px;
  }
}
</style>
