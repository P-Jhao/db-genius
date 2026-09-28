import { ref } from 'vue'
import { streamChat } from '../api/chat'
import { useChatStore } from '../stores/chat'
import type { UnifiedChatRequest, SseEvent } from '../types'

export function useSse() {
  const chatStore = useChatStore()
  const abortController = ref<AbortController | null>(null)
  const error = ref<string | null>(null)

  function send(body: UnifiedChatRequest) {
    error.value = null
    chatStore.isStreaming = true
    const assistantMsg = chatStore.addAssistantMessage()

    abortController.value = streamChat(
      body,
      (event: SseEvent) => {
        chatStore.handleSseEvent(event)
      },
      (err) => {
        error.value = err.message || 'Stream connection failed'
        assistantMsg.streaming = false
        chatStore.isStreaming = false
      }
    )
  }

  function abort() {
    abortController.value?.abort()
    abortController.value = null
    chatStore.isStreaming = false
    const lastMsg = chatStore.messages[chatStore.messages.length - 1]
    if (lastMsg?.role === 'assistant') {
      lastMsg.streaming = false
    }
  }

  return { send, abort, error }
}
