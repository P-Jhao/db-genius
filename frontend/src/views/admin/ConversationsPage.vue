<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Message, Modal } from '@arco-design/web-vue'
import type { ClarifyContent, ConversationVO, IntentType, SseEvent } from '../../types'
import { getConversations, deleteConversation, getMessages } from '../../api/chat'
import type { Message as MessageType } from '../../types'
import { useChatStore } from '../../stores/chat'
import type { ChatMessage } from '../../stores/chat'
import ReasoningCard from '../../components/chat/ReasoningCard.vue'

const { t, locale } = useI18n()
const router = useRouter()
const chatStore = useChatStore()
const conversations = ref<ConversationVO[]>([])
const loading = ref(false)
const msgDrawer = ref(false)
const currentMessages = ref<MessageType[]>([])
const currentTitle = ref('')
const msgLoading = ref(false)

const typeMap = computed<Record<string, { label: string; color: string }>>(() => ({
  simple_chat: { label: t('admin.conversations.type.simple_chat'), color: 'arcoblue' },
  sql_query: { label: t('admin.conversations.type.sql_query'), color: 'arcoblue' },
  workflow: { label: t('admin.conversations.type.workflow'), color: 'orangered' },
  db_compare: { label: t('admin.conversations.type.db_compare'), color: 'green' },
}))

const msgTypeMap = computed<Record<string, { label: string; color: string }>>(() => ({
  user: { label: t('admin.conversations.msgType.user'), color: 'arcoblue' },
  reasoning: { label: t('admin.conversations.msgType.reasoning'), color: 'purple' },
  thinking: { label: t('admin.conversations.msgType.thinking'), color: 'arcoblue' },
  classifying: { label: t('admin.conversations.msgType.classifying'), color: 'arcoblue' },
  classified: { label: t('admin.conversations.msgType.classified'), color: 'arcoblue' },
  clarify: { label: t('admin.conversations.msgType.clarify'), color: 'orange' },
  routing: { label: t('admin.conversations.msgType.routing'), color: 'gold' },
  step: { label: t('admin.conversations.msgType.step'), color: 'purple' },
  sql: { label: t('admin.conversations.msgType.sql'), color: 'purple' },
  result: { label: t('admin.conversations.msgType.result'), color: 'cyan' },
  file_parsed: { label: t('admin.conversations.msgType.file_parsed'), color: 'cyan' },
  content: { label: t('admin.conversations.msgType.content'), color: 'gray' },
  tool: { label: t('admin.conversations.msgType.tool'), color: 'cyan' },
  summary: { label: t('admin.conversations.msgType.summary'), color: 'green' },
  error: { label: t('admin.conversations.msgType.error'), color: 'red' },
  done: { label: t('admin.conversations.msgType.done'), color: 'gray' },
}))

function msgTypeLabel(type: string | null) {
  if (!type) return ''
  return msgTypeMap.value[type]?.label || type
}

function msgTypeColor(type: string | null) {
  if (!type) return 'gray'
  return msgTypeMap.value[type]?.color || 'gray'
}

async function load() {
  loading.value = true
  try {
    const res = await getConversations()
    conversations.value = res.data
  } catch (err: unknown) {
    Message.error((err as Error).message || t('admin.conversations.loadFailed'))
  } finally {
    loading.value = false
  }
}

async function viewMessages(conv: ConversationVO) {
  currentTitle.value = conv.title
  msgLoading.value = true
  msgDrawer.value = true
  try {
    const res = await getMessages(conv.id)
    currentMessages.value = res.data
  } catch (err: unknown) {
    Message.error((err as Error).message || t('admin.conversations.loadMessagesFailed'))
  } finally {
    msgLoading.value = false
  }
}

function handleDelete(conv: ConversationVO) {
  Modal.warning({
    title: t('admin.conversations.deleteConfirmTitle'),
    content: t('admin.conversations.deleteConfirmContent', { title: conv.title }),
    okText: t('admin.conversations.deleteText'),
    okButtonProps: { status: 'danger' },
    async onOk() {
      try {
        await deleteConversation(conv.id)
        Message.success(t('admin.conversations.deleteSuccess'))
        await load()
      } catch (err: unknown) {
        Message.error((err as Error).message || t('admin.conversations.deleteFailed'))
      }
    },
  })
}

function goChat() {
  router.push('/admin/chat')
}

function toSseEvent(m: MessageType, type: SseEvent['type']): SseEvent {
  return {
    taskId: '',
    step: m.step ?? 0,
    type,
    content: m.content,
    timestamp: m.createdAt ? new Date(m.createdAt).getTime() : Date.now(),
  }
}

function isIntentType(value: unknown): value is IntentType {
  return value === 'simple_chat' || value === 'sql_query' || value === 'workflow' || value === 'db_compare'
}

function parseClarifyContent(content: string): ClarifyContent {
  const parsed: unknown = JSON.parse(content)
  if (parsed === null || typeof parsed !== 'object') {
    throw new Error('Invalid clarification history content')
  }
  const value = parsed as Record<string, unknown>
  if (typeof value.question !== 'string' || typeof value.reasoning !== 'string' ||
      !Array.isArray(value.options) || !value.options.every((option: unknown) => {
        if (option === null || typeof option !== 'object') return false
        const item = option as Record<string, unknown>
        return isIntentType(item.intent) && typeof item.label === 'string'
      })) {
    throw new Error('Invalid clarification history content')
  }
  return parsed as ClarifyContent
}

// 归并历史消息：user 行切分回合，连续 assistant/tool 行合并为一条气泡的 blocks 时间线
function buildChatMessages(list: MessageType[]): ChatMessage[] {
  const msgs: ChatMessage[] = []
  let current: ChatMessage | null = null

  for (const m of list) {
    const ts = m.createdAt ? new Date(m.createdAt).getTime() : Date.now()

    if (m.role === 'user') {
      msgs.push({
        id: crypto.randomUUID(),
        role: 'user',
        content: m.content,
        blocks: [],
        streaming: false,
        timestamp: ts,
      })
      current = null
      continue
    }

    if (m.role === 'tool') {
      current?.blocks.push({ kind: 'event', event: toSseEvent(m, 'step') })
      continue
    }

    if (m.role !== 'assistant') continue

    if (!current) {
      current = {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: '',
        blocks: [],
        streaming: false,
        timestamp: ts,
      }
      msgs.push(current)
    }

    // 后端将每步思考内容存在 reasoningContent 字段里，作为独立思考块插在对应事件块之前
    if (m.reasoningContent) {
      current.blocks.push({ kind: 'reasoning', text: m.reasoningContent, done: true })
    }

    switch (m.type) {
      case 'reasoning':
        current.blocks.push({ kind: 'reasoning', text: m.content, done: true })
        break
      case 'summary':
        current.content = m.content
        current.blocks.push({ kind: 'summary', text: m.content, done: true, timestamp: ts })
        break
      case 'content':
        current.content += m.content
        break
      case 'step':
      case 'sql':
      case 'result':
      case 'file_parsed':
        current.blocks.push({ kind: 'event', event: toSseEvent(m, 'step') })
        break
      case 'error':
        current.blocks.push({ kind: 'event', event: toSseEvent(m, 'error') })
        break
      case 'clarify':
        current.blocks.push({
          kind: 'event',
          event: { ...toSseEvent(m, 'clarify'), content: parseClarifyContent(m.content) },
        })
        break
      default:
        // classifying/classified/routing/thinking/done 等瞬时状态不回放
        break
    }
  }
  return msgs
}

async function continueChat(conv: ConversationVO) {
  try {
    const res = await getMessages(conv.id)
    chatStore.openConversation(conv, buildChatMessages(res.data))
    router.push('/admin/chat')
  } catch (err: unknown) {
    Message.error((err as Error).message || t('admin.conversations.loadMessagesFailed'))
  }
}

function formatTime(dateStr: string) {
  return new Date(dateStr).toLocaleString(locale.value)
}

onMounted(load)
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2>{{ $t('admin.conversations.title') }}</h2>
        <p class="page-desc">{{ $t('admin.conversations.desc') }}</p>
      </div>
      <a-button type="primary" @click="goChat">
        <template #icon><icon-plus /></template>
        {{ $t('admin.conversations.newConversation') }}
      </a-button>
    </div>

    <a-spin :loading="loading" style="width: 100%">
      <a-table
        :data="conversations"
        :bordered="false"
        :pagination="{ pageSize: 20 }"
        row-key="id"
      >
        <template #columns>
          <a-table-column :title="$t('admin.conversations.colTitle')" data-index="title">
            <template #cell="{ record }">
              <a-link @click="viewMessages(record)">{{ record.title }}</a-link>
            </template>
          </a-table-column>
          <a-table-column :title="$t('admin.conversations.colType')" data-index="type" :width="120">
            <template #cell="{ record }">
              <a-tag :color="typeMap[record.type]?.color">
                {{ typeMap[record.type]?.label || record.type }}
              </a-tag>
            </template>
          </a-table-column>
          <a-table-column :title="$t('admin.conversations.colDbs')" data-index="dbConfigIds" :width="140">
            <template #cell="{ record }">
              <span class="text-muted">{{ record.dbConfigIds }}</span>
            </template>
          </a-table-column>
          <a-table-column :title="$t('admin.conversations.colCreatedAt')" data-index="createdAt" :width="180">
            <template #cell="{ record }">
              <span class="text-muted">{{ formatTime(record.createdAt) }}</span>
            </template>
          </a-table-column>
          <a-table-column :title="$t('admin.conversations.colActions')" :width="140" align="right">
            <template #cell="{ record }">
              <a-button size="small" type="text" @click="viewMessages(record)">
                <template #icon><icon-eye /></template>
              </a-button>
              <a-tooltip :content="$t('admin.conversations.continueChat')">
                <a-button size="small" type="text" @click="continueChat(record)">
                  <template #icon><icon-message /></template>
                </a-button>
              </a-tooltip>
              <a-button size="small" type="text" status="danger" @click="handleDelete(record)">
                <template #icon><icon-delete /></template>
              </a-button>
            </template>
          </a-table-column>
        </template>
        <template #empty>
          <a-empty :description="$t('admin.conversations.emptyDesc')">
            <template #image>
              <icon-message :size="48" :style="{ color: 'var(--color-text-4)' }" />
            </template>
            <a-button type="primary" @click="goChat">{{ $t('admin.conversations.startChat') }}</a-button>
          </a-empty>
        </template>
      </a-table>
    </a-spin>

    <a-drawer
      v-model:visible="msgDrawer"
      :title="currentTitle"
      :width="640"
      :footer="false"
    >
      <a-spin :loading="msgLoading" style="width: 100%">
        <div class="message-list">
          <div
            v-for="msg in currentMessages"
            :key="msg.id"
            class="message-item"
            :class="msg.role"
          >
            <div class="message-badge">
              <a-tag v-if="msg.type" size="small" :color="msgTypeColor(msg.type)">
                {{ msgTypeLabel(msg.type) }}
              </a-tag>
              <span v-if="msg.step !== null" class="step-badge">Step {{ msg.step }}</span>
            </div>
            <div class="message-content">
              <ReasoningCard v-if="msg.reasoningContent" :content="msg.reasoningContent" />
              <pre>{{ msg.content }}</pre>
            </div>
            <div class="message-time">{{ formatTime(msg.createdAt) }}</div>
          </div>
          <a-empty v-if="currentMessages.length === 0 && !msgLoading" :description="$t('admin.conversations.emptyMessages')" />
        </div>
      </a-spin>
    </a-drawer>
  </div>
</template>

<style scoped lang="scss">
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 24px;

  h2 {
    font-size: 20px;
    font-weight: 600;
    margin-bottom: 4px;
  }

  .page-desc {
    font-size: 13px;
    color: var(--color-text-3);
  }
}

.text-muted {
  color: var(--color-text-3);
  font-size: 13px;
}

.message-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.message-item {
  padding: 12px 16px;
  border-radius: 8px;
  border: 1px solid var(--color-border-1);

  &.user {
    background: #e8f3ff;
    border-color: #bdd9fc;
  }

  &.assistant {
    background: #fff;
  }

  .message-badge {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 8px;
  }

  .step-badge {
    font-size: 11px;
    color: var(--color-text-4);
  }

  .message-content {
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

  .message-time {
    margin-top: 8px;
    font-size: 11px;
    color: var(--color-text-4);
  }
}

@media (max-width: 768px) {
  .page-header {
    flex-direction: column;
    gap: 12px;
  }
}
</style>
