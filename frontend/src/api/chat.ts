import { fetchEventSource } from '@microsoft/fetch-event-source'
import { useUserStore } from '../stores/user'
import { handleUnauthorized } from '../utils/auth'
import { i18n, getCurrentLocale } from '../i18n'
import type { UnifiedChatRequest, SseEvent, R, ConversationVO, Message, CompressResultVO } from '../types'

const baseUrl = import.meta.env.VITE_API_BASE_URL

function getHeaders(): Record<string, string> {
  const userStore = useUserStore()
  return {
    'Content-Type': 'application/json',
    Authorization: userStore.token || '',
    // SSE 不经 axios 拦截器，需单独携带语言
    'Accept-Language': getCurrentLocale(),
  }
}

export function streamChat(
  body: UnifiedChatRequest,
  onEvent: (event: SseEvent) => void,
  onError: (err: Error) => void,
  onComplete: () => void
): AbortController {
  const ctrl = new AbortController()

  fetchEventSource(`${baseUrl}/chat`, {
    method: 'POST',
    headers: getHeaders(),
    body: JSON.stringify(body),
    signal: ctrl.signal,
    async onopen(response) {
      if (response.status === 401) {
        handleUnauthorized()
        throw new Error(i18n.global.t('chat.api.sessionExpired'))
      }
      if (!response.ok) throw new Error(`Chat request failed (${response.status})`)
      if (!response.headers.get('content-type')?.includes('text/event-stream')) {
        throw new Error('Chat endpoint did not return an event stream')
      }
    },
    onmessage(ev) {
      if (!ev.data) return
      const event: SseEvent = JSON.parse(ev.data)
      onEvent(event)
    },
    onerror(err) {
      throw err // stop retry
    },
    openWhenHidden: true,
  })
    .then(() => {
      if (!ctrl.signal.aborted) onComplete()
    })
    .catch((error: unknown) => {
      if (ctrl.signal.aborted) return
      onError(error instanceof Error ? error : new Error(String(error)))
    })

  return ctrl
}

export function getConversations() {
  return import('./request').then((m) =>
    m.default.get<unknown, R<ConversationVO[]>>('/chat/conversations')
  )
}

export function getMessages(conversationId: number) {
  return import('./request').then((m) =>
    m.default.get<unknown, R<Message[]>>(`/chat/conversations/${conversationId}/messages`)
  )
}

export function deleteConversation(id: number) {
  return import('./request').then((m) =>
    m.default.delete<unknown, R<null>>(`/chat/conversations/${id}`)
  )
}

export function compressConversation(id: number, targetTokens?: number | null) {
  return import('./request').then((m) =>
    m.default.post<unknown, R<CompressResultVO>>(
      `/chat/conversations/${id}/compress`,
      targetTokens != null ? { targetTokens } : {}
    )
  )
}
