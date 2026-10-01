import { watch } from 'vue'

export function watchAssistantStreaming(store, assistantMessageId, onChange) {
  return watch(
    () => store.messages.find((message) => message.id === assistantMessageId)?.streaming,
    onChange,
    { flush: 'sync' },
  )
}
