import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { streamChat, type StreamEvent } from '@/lib/api'

export type Message = {
  id: string
  role: 'user' | 'assistant'
  content: string
  reasoning?: string
  status: 'streaming' | 'completed' | 'failed' | 'cancelled'
}

export const useChatStore = defineStore('chat', () => {
  const messages = ref<Message[]>([])
  const mode = ref<'chat' | 'work'>('chat')
  const agentType = ref<'image' | 'slides' | 'research'>('image')
  const controller = ref<AbortController | null>(null)
  const isStreaming = computed(() => controller.value !== null)

  async function send(content: string) {
    if (!content.trim() || isStreaming.value) return
    messages.value.push({
      id: crypto.randomUUID(),
      role: 'user',
      content: content.trim(),
      status: 'completed',
    })
    const answer: Message = {
      id: crypto.randomUUID(),
      role: 'assistant',
      content: '',
      reasoning: '',
      status: 'streaming',
    }
    messages.value.push(answer)
    controller.value = new AbortController()

    const onEvent = (event: StreamEvent) => {
      if (event.type === 'message.delta') answer.content += event.delta
      if (event.type === 'reasoning.delta') answer.reasoning += event.delta
      if (event.type === 'completed') answer.status = 'completed'
      if (event.type === 'failed') {
        answer.status = 'failed'
        answer.content = event.message
      }
    }
    try {
      await streamChat(
        {
          content: content.trim(),
          mode: mode.value,
          ...(mode.value === 'work' ? { agent_type: agentType.value } : {}),
        },
        onEvent,
        controller.value.signal,
      )
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        answer.status = 'cancelled'
      } else {
        answer.status = 'failed'
        answer.content = error instanceof Error ? error.message : '请求失败'
      }
    } finally {
      controller.value = null
    }
  }

  function stop() {
    controller.value?.abort()
  }

  function clear() {
    if (!isStreaming.value) messages.value = []
  }

  return { messages, mode, agentType, isStreaming, send, stop, clear }
})

