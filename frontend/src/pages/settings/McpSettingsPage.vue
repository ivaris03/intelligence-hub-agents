<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { settingsApi, type AppSettings } from '@/lib/api'

const settings = ref<AppSettings | null>(null)
const loading = ref(true)
const error = ref('')

onMounted(async () => {
  try {
    settings.value = await settingsApi.get()
  } catch (cause) {
    report(cause)
  } finally {
    loading.value = false
  }
})

function report(cause: unknown) {
  error.value = cause instanceof Error ? cause.message : '操作失败'
}

async function toggleWebSearch() {
  if (!settings.value) return
  try {
    settings.value = await settingsApi.update({ web_search_enabled: !settings.value.web_search_enabled })
  } catch (cause) {
    report(cause)
  }
}
</script>

<template>
  <div v-if="error" class="global-error"><span>{{ error }}</span><button @click="error = ''">×</button></div>
  <p v-if="loading" class="loading-state"><span></span>读取设置…</p>

  <section v-if="settings" class="settings-section">
    <header><div><span class="section-kicker">MCP</span><h2>MCP 服务</h2><p>查看外部能力的连接状态，并控制它们是否可在对话中使用。</p></div></header>
    <div class="settings-card">
      <div><h3>Tavily Search</h3><p>仅在消息明确要求联网搜索时调用 Tavily MCP。</p></div>
      <div class="setting-control">
        <span class="status-badge" :class="{ ready: settings.tavily_ready }">{{ settings.tavily_ready ? '已连接' : '未配置' }}</span>
        <label class="switch"><input :checked="settings.web_search_enabled" type="checkbox" aria-label="启用 Tavily MCP" @change="toggleWebSearch" /><span></span></label>
      </div>
    </div>
  </section>
</template>
