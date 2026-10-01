import { ref } from 'vue'
import { streamChat } from '../api/chat'
import { useChatStore } from '../stores/chat'
import type { ChatMessage } from '../stores/chat'
import type { UnifiedChatRequest, SseEvent } from '../types'

export function useSse() {
  const chatStore = useChatStore()
  const abortController = ref<AbortController | null>(null)
  const error = ref<string | null>(null)
  let activeMessage: ChatMessage | null = null

  function send(body: UnifiedChatRequest) {
    if (abortController.value) abort()
    error.value = null
    const addedMessage = chatStore.addAssistantMessage()
    const assistantMsg = chatStore.messages.find((message) => message.id === addedMessage.id)
    if (!assistantMsg) throw new Error(`Assistant message ${addedMessage.id} was not added to the chat store`)
    chatStore.isStreaming = true
    activeMessage = assistantMsg

    const controller = streamChat(
      body,
      (event: SseEvent) => {
        if (abortController.value !== controller) return
        chatStore.handleSseEvent(event)
      },
      (err) => {
        if (abortController.value !== controller) return
        error.value = err.message || 'Stream connection failed'
        assistantMsg.streaming = false
        chatStore.isStreaming = false
        abortController.value = null
        activeMessage = null
      },
      () => {
        if (abortController.value !== controller) return
        assistantMsg.streaming = false
        chatStore.isStreaming = false
        abortController.value = null
        activeMessage = null
      }
    )
    abortController.value = controller
  }

  function abort() {
    abortController.value?.abort()
    abortController.value = null
    chatStore.isStreaming = false
    if (activeMessage) activeMessage.streaming = false
    activeMessage = null
  }

  return { send, abort, error }
}
