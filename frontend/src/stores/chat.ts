import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { SseEvent, ConversationVO, TokenUsageVO } from '../types'
import { getConversations, deleteConversation } from '../api/chat'

export type ChatBlock =
  | { kind: 'reasoning'; text: string; done: boolean }
  | { kind: 'summary'; text: string; done: boolean; timestamp: number }
  | { kind: 'event'; event: SseEvent }

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  blocks: ChatBlock[]
  streaming: boolean
  timestamp: number
  /** 本轮 token 用量（usage 事件到达后填充，仅 assistant 消息） */
  usage?: TokenUsageVO | null
}

export const useChatStore = defineStore('chat', () => {
  const messages = ref<ChatMessage[]>([])
  const currentConversationId = ref<number | null>(null)
  const conversations = ref<ConversationVO[]>([])
  const isStreaming = ref(false)
  const currentTaskId = ref<string | null>(null)
  // ---- token / 上下文窗口状态 ----
  /** 当前上下文占用 token（最近一次 usage 事件的 contextTokens） */
  const contextTokens = ref(0)
  /** 当前模型最大上下文窗口，未知为 null */
  const contextWindow = ref<number | null>(null)
  /** 会话累计消耗 token */
  const conversationTotalTokens = ref(0)
  /** 上下文占用已越过 80% 阈值（用于首次弹窗提示去重） */
  const warnedAt80 = ref(false)
  let lastReasoningStep: number | null = null

  function addUserMessage(content: string): ChatMessage {
    const msg: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'user',
      content,
      blocks: [],
      streaming: false,
      timestamp: Date.now(),
    }
    messages.value.push(msg)
    return msg
  }

  function addAssistantMessage(): ChatMessage {
    lastReasoningStep = null
    const msg: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'assistant',
      content: '',
      blocks: [],
      streaming: true,
      timestamp: Date.now(),
    }
    messages.value.push(msg)
    return msg
  }

  function handleSseEvent(event: SseEvent) {
    // 会话 id 事件可能在 assistant 消息创建前到达，需优先处理
    if (event.type === 'conversation') {
      currentConversationId.value = Number(event.content)
      return
    }

    const lastMsg = messages.value[messages.value.length - 1]
    if (!lastMsg || lastMsg.role !== 'assistant') return

    currentTaskId.value = event.taskId

    if (event.type === 'reasoning') {
      const text = (event.content as string) || ''
      const lastBlock = lastMsg.blocks[lastMsg.blocks.length - 1]
      // 同一 step 的增量（simple_chat 流式）追加到当前 reasoning block；
      // step 变化（Agent 流程每步一块）则关闭旧块、开新块
      if (lastBlock?.kind === 'reasoning' && !lastBlock.done && lastReasoningStep === event.step) {
        lastBlock.text += text
      } else {
        closeOpenReasoning(lastMsg)
        lastMsg.blocks.push({ kind: 'reasoning', text, done: false })
      }
      lastReasoningStep = event.step
      return
    }

    // 思考阶段结束：出现非 reasoning 的后续事件
    closeOpenReasoning(lastMsg)

    if (event.type === 'usage') {
      // usage 事件先于 done 到达；只更新用量状态，不 push blocks（避免被 SseStepCard 渲染）
      const usage = event.content as TokenUsageVO
      if (usage && typeof usage === 'object') {
        lastMsg.usage = usage
        if (usage.contextTokens > 0) {
          contextTokens.value = usage.contextTokens
        }
        if (usage.contextWindow != null) {
          contextWindow.value = usage.contextWindow
        }
        if (usage.conversationTotalTokens != null) {
          conversationTotalTokens.value = usage.conversationTotalTokens
        }
        // 占用回落到阈值以下时复位，允许下次越线再次弹窗
        if (contextWindow.value && contextTokens.value / contextWindow.value < 0.8) {
          warnedAt80.value = false
        }
      }
      return
    }

    if (event.type === 'done' || event.type === 'aborted') {
      lastMsg.streaming = false
      isStreaming.value = false
      return
    }

    if (event.type === 'error') {
      lastMsg.blocks.push({ kind: 'event', event })
      lastMsg.streaming = false
      isStreaming.value = false
      return
    }

    if (event.type === 'clarify') {
      lastMsg.blocks.push({ kind: 'event', event })
      lastMsg.streaming = false
      isStreaming.value = false
      return
    }

    if (event.type === 'content') {
      const text = (event.content as string) || ''
      lastMsg.content += text
      return
    }

    if (event.type === 'summary_delta') {
      const text = (event.content as string) || ''
      const summaryBlock = findLastSummaryBlock(lastMsg)
      // 仅向未定稿块追加；定稿后到达的乱序 delta 直接忽略
      if (summaryBlock && !summaryBlock.done) {
        summaryBlock.text += text
        lastMsg.content += text
      } else if (!summaryBlock) {
        lastMsg.blocks.push({ kind: 'summary', text, done: false, timestamp: event.timestamp })
        lastMsg.content += text
      }
      return
    }

    if (event.type === 'summary') {
      // 终态全量内容为权威定稿：覆盖流式增量结果，避免重复拼接
      const text = (event.content as string) || ''
      const summaryBlock = findLastSummaryBlock(lastMsg)
      if (summaryBlock) {
        summaryBlock.text = text
        summaryBlock.done = true
        summaryBlock.timestamp = event.timestamp
      } else {
        lastMsg.blocks.push({ kind: 'summary', text, done: true, timestamp: event.timestamp })
      }
      lastMsg.content = text
      return
    }

    lastMsg.blocks.push({ kind: 'event', event })
  }

  function closeOpenReasoning(msg: ChatMessage) {
    const lastBlock = msg.blocks[msg.blocks.length - 1]
    if (lastBlock?.kind === 'reasoning' && !lastBlock.done) {
      lastBlock.done = true
    }
  }

  function findLastSummaryBlock(msg: ChatMessage) {
    for (let i = msg.blocks.length - 1; i >= 0; i--) {
      const block = msg.blocks[i]
      if (block.kind === 'summary') return block
    }
    return null
  }

  function clearChat() {
    messages.value = []
    currentConversationId.value = null
    currentTaskId.value = null
    contextTokens.value = 0
    conversationTotalTokens.value = 0
    warnedAt80.value = false
    // contextWindow 保留：属于模型配置，与具体会话无关
  }

  /** 打开历史会话：恢复消息列表与持久化的 token 统计（contextWindow 保留当前模型配置值） */
  function openConversation(conversation: ConversationVO, msgs: ChatMessage[]) {
    clearChat()
    currentConversationId.value = conversation.id
    messages.value = msgs
    contextTokens.value = conversation.contextTokens ?? 0
    conversationTotalTokens.value = conversation.totalTokens ?? 0
  }

  function setMessages(msgs: ChatMessage[]) {
    messages.value = msgs
  }

  async function loadConversations() {
    try {
      const res = await getConversations()
      conversations.value = res.data
    } catch {
      conversations.value = []
    }
  }

  async function removeConversation(id: number) {
    await deleteConversation(id)
    conversations.value = conversations.value.filter((c) => c.id !== id)
    if (currentConversationId.value === id) {
      clearChat()
    }
  }

  return {
    messages,
    currentConversationId,
    conversations,
    isStreaming,
    currentTaskId,
    contextTokens,
    contextWindow,
    conversationTotalTokens,
    warnedAt80,
    addUserMessage,
    addAssistantMessage,
    handleSseEvent,
    clearChat,
    openConversation,
    setMessages,
    loadConversations,
    removeConversation,
  }
})
