<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { settingsApi, type AppSettings } from '@/lib/api'

const settings = ref<AppSettings | null>(null)
const loading = ref(true)
const error = ref('')

onMounted(async () => {
  try {
    settings.value = await settingsApi.get()
    applyTheme(settings.value.appearance)
  } catch (cause) {
    report(cause)
  } finally {
    loading.value = false
  }
})

function report(cause: unknown) {
  error.value = cause instanceof Error ? cause.message : '操作失败'
}

async function updateAppearance(appearance: AppSettings['appearance']) {
  try {
    settings.value = await settingsApi.update({ appearance })
    applyTheme(settings.value.appearance)
  } catch (cause) {
    report(cause)
  }
}

function applyTheme(theme: AppSettings['appearance']) {
  document.documentElement.dataset.theme = theme
}
</script>

<template>
  <div v-if="error" class="global-error"><span>{{ error }}</span><button @click="error = ''">×</button></div>
  <p v-if="loading" class="loading-state"><span></span>读取设置…</p>

  <section v-if="settings" class="settings-section">
    <header><div><span class="section-kicker">GENERAL</span><h2>通用</h2><p>管理 Hub 的外观和模型服务。</p></div></header>
    <div class="settings-card">
      <div><h3>外观</h3><p>选择系统、浅色或深色主题。</p></div>
      <select :value="settings.appearance" aria-label="外观主题" @change="updateAppearance(($event.target as HTMLSelectElement).value as AppSettings['appearance'])">
        <option value="system">跟随系统</option>
        <option value="light">浅色</option>
        <option value="dark">深色</option>
      </select>
    </div>
    <div class="settings-card">
      <div><h3>模型</h3><p>模型密钥仅从服务端环境变量读取，不会发送到浏览器。</p></div>
      <span class="status-badge" :class="{ ready: settings.model_ready }">{{ settings.model_ready ? 'Qwen 已连接' : '本地演示模式' }}</span>
    </div>
  </section>
</template>
