<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { memorySummaryApi, settingsApi, type AppSettings, type MemorySummary } from '@/lib/api'

const settings = ref<AppSettings | null>(null)
const memorySummary = ref<MemorySummary | null>(null)
const memoryDraft = ref('')
const loading = ref(true)
const error = ref('')
const clearMemoryArmed = ref(false)

onMounted(async () => {
  try {
    ;[settings.value, memorySummary.value] = await Promise.all([settingsApi.get(), memorySummaryApi.get()])
    memoryDraft.value = memorySummary.value.content
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

function sourceLabel(source: MemorySummary['source']) {
  return { manual: '设置页编辑', explicit: '对话指令', automatic: '闲置提炼' }[source]
}
</script>

<template>
  <div v-if="error" class="global-error"><span>{{ error }}</span><button @click="error = ''">×</button></div>
  <p v-if="loading" class="loading-state"><span></span>读取设置…</p>

  <section v-if="settings" class="settings-section">
    <header><div><span class="section-kicker">MEMORY</span><h2>用户记忆摘要</h2><p>每次对话都会将整份摘要注入 System Prompt；关闭后不提炼、不写入，也不注入。</p></div><label class="switch"><input :checked="settings.memory_enabled" type="checkbox" aria-label="启用 Memory" @change="toggleMemory" /><span></span></label></header>
    <form class="editor-card memory-summary-editor" @submit.prevent="saveMemorySummary">
      <label>摘要内容<textarea v-model="memoryDraft" :disabled="!settings.memory_enabled" rows="9" maxlength="4000" placeholder="例如：用户是一名 Python 开发者，偏好简洁、先给结论的回答。"></textarea></label>
      <small v-if="memorySummary">{{ sourceLabel(memorySummary.source) }} · {{ new Date(memorySummary.updated_at).toLocaleString() }}</small>
      <button class="primary-action" type="submit" :disabled="!settings.memory_enabled">保存摘要</button>
    </form>
    <div v-if="memoryDraft || memorySummary?.content" class="clear-memory-actions">
      <button v-if="!clearMemoryArmed" class="danger-outline" @click="clearMemoryArmed = true">清空记忆摘要</button>
      <template v-else><button class="danger-outline" @click="clearMemorySummary">确认清空</button><button @click="clearMemoryArmed = false">取消</button></template>
    </div>
  </section>
</template>
