<script setup lang="ts">
import { ref, computed, nextTick, watch, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { Message } from '@arco-design/web-vue'
import { useChatStore } from '../../stores/chat'
import type { ChatMessage } from '../../stores/chat'
import { useTrialStore } from '../../stores/trial'
import { useSse } from '../../composables/useSse'
import type { UploadedFile, IntentType, UnifiedChatRequest } from '../../types'
import MessageBubble from '../../components/chat/MessageBubble.vue'
import ContextUsageBar from '../../components/chat/ContextUsageBar.vue'
import DbSelector from '../../components/chat/DbSelector.vue'
import FileUploader from '../../components/chat/FileUploader.vue'

const { t } = useI18n()
const chatStore = useChatStore()
const trialStore = useTrialStore()
const { send, abort, error } = useSse()

const inputText = ref('')
const selectedDbIds = ref<number[]>([])
const preDbId = ref<number | null>(null)
const testDbId = ref<number | null>(null)
const compareMode = ref(false)
const uploadedFiles = ref<UploadedFile[]>([])
const messagesContainer = ref<HTMLElement | null>(null)
const textareaRef = ref<HTMLElement | null>(null)

const isTrial = computed(() => trialStore.isTrial)
const inputPlaceholder = computed(() => t(trialStore.trialEnabled === false
  ? 'admin.chat.inputPlaceholder' : 'admin.chat.trialInputPlaceholder'))
const canUseRestrictedFeatures = computed(() => trialStore.isReady && !isTrial.value)

onMounted(() => {
  trialStore.loadTrialStatus()
})

watch(isTrial, (trial) => {
  if (trial && compareMode.value) {
    compareMode.value = false
    preDbId.value = null
    testDbId.value = null
  }
})

const canSend = computed(() => {
  if (chatStore.isStreaming) return false
  if (!inputText.value.trim()) return false
  if (compareMode.value) {
    return preDbId.value !== null && testDbId.value !== null
  }
  return true
})

const sendDisabledReason = computed(() => {
  if (!inputText.value.trim()) return t('admin.chat.inputEmpty')
  if (compareMode.value) {
    if (!preDbId.value || !testDbId.value) return t('admin.chat.selectCompareDbs')
  }
  return ''
})

function scrollToBottom() {
  nextTick(() => {
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  })
}

watch(() => chatStore.messages.length, scrollToBottom)
watch(
  () => {
    const last = chatStore.messages[chatStore.messages.length - 1]
    if (!last) return 0
    const lastBlock = last.blocks[last.blocks.length - 1]
    const reasoningLen = lastBlock?.kind === 'reasoning' ? lastBlock.text.length : 0
    return last.blocks.length * 100000 + reasoningLen + last.content.length
  },
  scrollToBottom
)

function buildRequest(message: string, confirmedIntent?: IntentType | null): UnifiedChatRequest {
  return {
    message,
    conversationId: chatStore.currentConversationId,
    dbConfigIds: compareMode.value ? null : selectedDbIds.value.length > 0 ? selectedDbIds.value : null,
    preDbConfigId: compareMode.value ? preDbId.value : null,
    testDbConfigId: compareMode.value ? testDbId.value : null,
    fileIds: uploadedFiles.value.length > 0 ? uploadedFiles.value.map((f) => f.id) : null,
    confirmedIntent: confirmedIntent || null,
  }
}

function handleSend() {
  if (!canSend.value) return

  const userText = inputText.value.trim()
  chatStore.addUserMessage(userText)
  inputText.value = ''

  scrollToBottom()
  send(buildRequest(userText))
}

function handleConfirmIntent(message: ChatMessage, intent: string) {
  if (intent !== 'simple_chat' && intent !== 'sql_query' &&
      intent !== 'workflow' && intent !== 'db_compare') {
    throw new Error(`Invalid confirmed intent: ${intent}`)
  }
  const index = chatStore.messages.findIndex((item) => item.id === message.id)
  if (index < 0) throw new Error('Clarification message is no longer in this conversation')
  const userMessage = chatStore.messages.slice(0, index).reverse().find((item) => item.role === 'user')
  if (!userMessage) throw new Error('Clarification has no preceding user message')
  send(buildRequest(userMessage.content, intent))
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}

function handleNewChat() {
  chatStore.clearChat()
  selectedDbIds.value = []
  preDbId.value = null
  testDbId.value = null
  compareMode.value = false
  uploadedFiles.value = []
}

function handleFilesChanged(files: UploadedFile[]) {
  uploadedFiles.value = files
}

function handleStop() {
  abort()
}

function handleCompareToggle() {
  compareMode.value = !compareMode.value
  selectedDbIds.value = []
  preDbId.value = null
  testDbId.value = null
}

const agentCapabilityTooltip = computed(() => t('admin.chat.capabilityTooltip'))
</script>

<template>
  <div class="chat-page">
    <div class="chat-toolbar">
      <div class="toolbar-left">
        <a-button type="text" size="small" @click="handleNewChat">
          <template #icon><icon-plus /></template>
          {{ $t('admin.chat.newChat') }}
        </a-button>
      </div>
      <div v-if="chatStore.currentTaskId" class="toolbar-right">
        <a-tag size="small" color="gray">Task: {{ chatStore.currentTaskId.slice(0, 8) }}</a-tag>
      </div>
    </div>

    <div ref="messagesContainer" class="chat-messages">
      <div v-if="chatStore.messages.length === 0" class="empty-chat">
        <div class="empty-icon">
          <svg width="64" height="64" viewBox="0 0 64 64" fill="none">
            <rect width="64" height="64" rx="16" fill="#F2F3F5"/>
            <path d="M20 26h24M20 32h16M20 38h20" stroke="#C9CDD4" stroke-width="2" stroke-linecap="round"/>
            <circle cx="48" cy="44" r="8" fill="#165DFF" opacity="0.15"/>
            <path d="M45 44h6M48 41v6" stroke="#165DFF" stroke-width="1.5" stroke-linecap="round"/>
          </svg>
        </div>
        <h3>{{ $t('admin.chat.emptyTitle') }}</h3>
        <p>{{ $t('admin.chat.emptyDesc') }}</p>
      </div>

      <MessageBubble
        v-for="msg in chatStore.messages"
        :key="msg.id"
        :message="msg"
        @confirm-intent="intent => handleConfirmIntent(msg, intent)"
      />
    </div>

    <div class="chat-input-area">
      <div v-if="error" class="input-error">
        <icon-exclamation-circle />
        <span>{{ error }}</span>
      </div>

      <ContextUsageBar />

      <div class="control-row">
        <FileUploader @files-changed="handleFilesChanged" />
        <DbSelector
          v-if="!compareMode"
          v-model="selectedDbIds"
          variant="multi"
        />
        <DbSelector
          v-else
          v-model:pre-id="preDbId"
          v-model:test-id="testDbId"
          variant="compare"
        />
        <a-tooltip v-if="canUseRestrictedFeatures" :content="$t('admin.chat.compareTooltip')" position="top">
          <a-button
            size="small"
            :type="compareMode ? 'primary' : 'text'"
            @click="handleCompareToggle"
          >
            <template #icon><icon-swap /></template>
            {{ compareMode ? $t('admin.chat.compareOn') : $t('admin.chat.compareOff') }}
          </a-button>
        </a-tooltip>
      </div>

      <div class="input-row">
        <a-textarea
          ref="textareaRef"
          v-model="inputText"
          :placeholder="inputPlaceholder"
          :auto-size="{ minRows: 1, maxRows: 4 }"
          :disabled="chatStore.isStreaming"
          @keydown="handleKeydown"
        />

        <div class="input-actions">
          <a-tooltip position="top">
            <template #content>
              <div class="capability-tooltip">{{ agentCapabilityTooltip }}</div>
            </template>
            <a-button type="text" size="small" class="info-btn">
              <template #icon><icon-info-circle /></template>
            </a-button>
          </a-tooltip>

          <a-button
            v-if="chatStore.isStreaming"
            type="primary"
            status="danger"
            @click="handleStop"
          >
            <template #icon><icon-pause /></template>
            {{ $t('admin.chat.stop') }}
          </a-button>
          <a-tooltip v-else :content="sendDisabledReason" :disabled="canSend" position="top">
            <a-button
              type="primary"
              :disabled="!canSend"
              @click="handleSend"
            >
              <template #icon><icon-send /></template>
              {{ $t('admin.chat.send') }}
            </a-button>
          </a-tooltip>
        </div>
      </div>
      <div class="input-hint">
        {{ $t('admin.chat.hint') }}
        <span v-if="uploadedFiles.length > 0" class="hint-tag">
          <icon-file /> {{ $t('admin.chat.filesUploaded', { count: uploadedFiles.length }) }}
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.chat-page {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--color-bg-1);
}

.chat-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  border-bottom: 1px solid var(--color-border-1);
  background: #fff;
  flex-shrink: 0;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

.empty-chat {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  text-align: center;
  color: var(--color-text-3);

  .empty-icon {
    margin-bottom: 16px;
  }

  h3 {
    font-size: 18px;
    font-weight: 600;
    color: var(--color-text-1);
    margin-bottom: 8px;
  }

  p {
    font-size: 14px;
    max-width: 400px;
    line-height: 1.5;
  }
}

.chat-input-area {
  margin: 0 16px 32px;
  padding: 12px 16px;
  border: 1px solid var(--color-border-1);
  border-radius: 12px;
  background: #fff;
  flex-shrink: 0;
}

.input-error {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  margin-bottom: 8px;
  border-radius: 6px;
  background: #fff2f0;
  color: #F53F3F;
  font-size: 13px;
}

.control-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 12px;

  :deep(.db-selector) {
    width: 200px;
  }

  :deep(.db-selector--compare) {
    width: 320px;
  }
}

.input-row {
  display: flex;
  gap: 8px;
  align-items: flex-end;
}

:deep(.arco-textarea-wrapper) {
  flex: 1;
  min-width: 0;
}

.input-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.info-btn {
  color: var(--color-text-3);

  &:hover {
    color: rgb(var(--primary-6));
  }
}

.capability-tooltip {
  white-space: pre-line;
  line-height: 1.6;
  max-width: 280px;
}

.input-hint {
  margin-top: 8px;
  font-size: 12px;
  color: var(--color-text-4);
  display: flex;
  align-items: center;
  gap: 12px;
}

.hint-tag {
  display: flex;
  align-items: center;
  gap: 4px;
}

@media (max-width: 768px) {
  .chat-toolbar {
    padding: 8px 12px;
  }

  .chat-messages {
    padding: 12px;
  }

  .chat-input-area {
    margin: 0 12px 24px;
    padding: 10px 12px;
  }

  .control-row {
    width: 100%;

    :deep(.db-selector),
    :deep(.db-selector--compare) {
      flex: 1;
      width: auto;
      min-width: 140px;
    }
  }

  .input-row {
    flex-wrap: wrap;
  }

  :deep(.arco-textarea-wrapper) {
    width: 100%;
    flex: auto;
  }

  .input-actions {
    margin-left: auto;
  }
}
</style>
