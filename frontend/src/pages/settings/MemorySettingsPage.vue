<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'

import {
  memorySummaryApi,
  settingsApi,
  type AppSettings,
  type MemoryChatMessage,
  type MemorySummary,
} from '@/lib/api'

const settings = ref<AppSettings | null>(null)
const memorySummary = ref<MemorySummary | null>(null)
const memoryDraft = ref('')
const loading = ref(true)
const error = ref('')
const clearMemoryArmed = ref(false)
const memoryMessages = ref<MemoryChatMessage[]>([])
const chatDraft = ref('')
const sending = ref(false)
const chatScroll = ref<HTMLElement | null>(null)
const refining = ref(false)
const refineNotice = ref('')

onMounted(async () => {
  try {
    ;[settings.value, memorySummary.value, memoryMessages.value] = await Promise.all([
      settingsApi.get(),
      memorySummaryApi.get(),
      memorySummaryApi.messages(),
    ])
    memoryDraft.value = memorySummary.value.content
    await scrollChat()
  } catch (cause) {
    report(cause)
  } finally {
    loading.value = false
  }
})

function report(cause: unknown) {
  error.value = cause instanceof Error ? cause.message : '操作失败'
}

async function toggleMemory() {
  if (!settings.value) return
  try {
    settings.value = await settingsApi.update({ memory_enabled: !settings.value.memory_enabled })
  } catch (cause) {
    report(cause)
  }
}

async function saveMemorySummary() {
  try {
    memorySummary.value = await memorySummaryApi.update(memoryDraft.value.trim())
    memoryDraft.value = memorySummary.value.content
  } catch (cause) {
    report(cause)
  }
}

async function clearMemorySummary() {
  try {
    await memorySummaryApi.clear()
    memoryDraft.value = ''
    if (memorySummary.value) memorySummary.value.content = ''
    clearMemoryArmed.value = false
  } catch (cause) {
    report(cause)
  }
}

async function refineMemorySummary() {
  if (refining.value || !settings.value?.memory_enabled) return
  refining.value = true
  refineNotice.value = ''
  error.value = ''
  try {
    const response = await memorySummaryApi.refine()
    memorySummary.value = response.summary
    memoryDraft.value = response.summary.content
    if (!response.processed_messages) {
      refineNotice.value = '没有待处理的对话消息'
    } else if (!response.added_facts) {
      refineNotice.value = `已处理 ${response.processed_messages} 条消息，没有发现新的稳定记忆`
    } else {
      refineNotice.value = `已处理 ${response.processed_messages} 条消息，新增 ${response.added_facts} 条记忆`
    }
  } catch (cause) {
    report(cause)
  } finally {
    refining.value = false
  }
}

async function sendMemoryMessage() {
  const content = chatDraft.value.trim()
  if (!content || sending.value || !settings.value?.memory_enabled) return
  sending.value = true
  error.value = ''
  try {
    const response = await memorySummaryApi.chat(content)
    memoryMessages.value.push(response.user_message, response.assistant_message)
    memorySummary.value = response.summary
    memoryDraft.value = response.summary.content
    chatDraft.value = ''
    await scrollChat()
  } catch (cause) {
    report(cause)
  } finally {
    sending.value = false
  }
}

async function clearMemoryMessages() {
  try {
    await memorySummaryApi.clearMessages()
    memoryMessages.value = []
  } catch (cause) {
    report(cause)
  }
}

async function scrollChat() {
  await nextTick()
  chatScroll.value?.scrollTo({ top: chatScroll.value.scrollHeight })
}

function handleChatKeydown(event: KeyboardEvent) {
  if (event.key !== 'Enter' || event.shiftKey) return
  event.preventDefault()
  void sendMemoryMessage()
}

function sourceLabel(source: MemorySummary['source']) {
  return { manual: '设置页编辑', explicit: '对话更新', automatic: '闲置提炼' }[source]
}
</script>

<template>
  <div v-if="error" class="global-error"><span>{{ error }}</span><button @click="error = ''">×</button></div>
  <p v-if="loading" class="loading-state"><span></span>读取设置…</p>

  <section v-if="settings" class="settings-section">
    <header><div><span class="section-kicker">MEMORY</span><h2>用户记忆摘要</h2><p>每次对话都会将整份摘要注入 System Prompt；关闭后不提炼、不写入，也不注入。</p></div><label class="switch"><input :checked="settings.memory_enabled" type="checkbox" aria-label="启用 Memory" @change="toggleMemory" /><span></span></label></header>
    <div class="memory-workspace">
      <form class="editor-card memory-summary-editor" @submit.prevent="saveMemorySummary">
        <header>
          <div><span class="section-kicker">SUMMARY</span><h3>当前摘要</h3></div>
          <button
            type="button"
            class="memory-refine-button"
            :disabled="refining || !settings.memory_enabled"
            @click="refineMemorySummary"
          >{{ refining ? '更新中…' : '更新记忆' }}</button>
        </header>
        <label>摘要内容<textarea v-model="memoryDraft" :disabled="!settings.memory_enabled" rows="12" maxlength="4000" placeholder="例如：用户是一名 Python 开发者，偏好简洁、先给结论的回答。"></textarea></label>
        <small v-if="memorySummary">{{ sourceLabel(memorySummary.source) }} · {{ new Date(memorySummary.updated_at).toLocaleString() }}</small>
        <small v-if="refineNotice" class="memory-refine-notice">{{ refineNotice }}</small>
        <button class="primary-action" type="submit" :disabled="!settings.memory_enabled">保存摘要</button>
      </form>

      <section class="memory-chat-panel" :class="{ disabled: !settings.memory_enabled }">
        <header>
          <div><span class="section-kicker">MEMORY CHAT</span><h3>和记忆聊聊</h3></div>
          <button v-if="memoryMessages.length" type="button" title="清空对话记录" aria-label="清空记忆对话记录" @click="clearMemoryMessages">清空</button>
        </header>
        <div ref="chatScroll" class="memory-chat-messages" aria-live="polite">
          <div v-if="!memoryMessages.length" class="memory-chat-empty">
            <span>◇</span>
            <p>问问我记住了什么，或直接告诉我需要更新的信息。</p>
          </div>
          <article v-for="message in memoryMessages" :key="message.id" class="memory-chat-message" :class="message.role">
            <div>{{ message.content }}</div>
            <small v-if="message.memory_changed">摘要已更新</small>
          </article>
          <article v-if="sending" class="memory-chat-message assistant pending"><div><i></i><i></i><i></i></div></article>
        </div>
        <form class="memory-chat-composer" @submit.prevent="sendMemoryMessage">
          <textarea
            v-model="chatDraft"
            rows="2"
            maxlength="4000"
            :disabled="!settings.memory_enabled || sending"
            placeholder="例如：我现在喜欢吃梨了"
            aria-label="与记忆摘要对话"
            @keydown="handleChatKeydown"
          ></textarea>
          <button type="submit" title="发送" aria-label="发送" :disabled="!chatDraft.trim() || sending || !settings.memory_enabled">↑</button>
        </form>
      </section>
    </div>
    <div v-if="memoryDraft || memorySummary?.content" class="clear-memory-actions">
      <button v-if="!clearMemoryArmed" class="danger-outline" @click="clearMemoryArmed = true">清空记忆摘要</button>
      <template v-else><button class="danger-outline" @click="clearMemorySummary">确认清空</button><button @click="clearMemoryArmed = false">取消</button></template>
    </div>
  </section>
</template>
