<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useAuth } from '@/features/auth/authStore'
import { settingsApi } from '@/lib/api'

const auth = useAuth()
const route = useRoute()
const router = useRouter()
const phone = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')

async function submit() {
  error.value = ''
  loading.value = true
  try {
    await auth.login(phone.value.trim(), password.value)
    const settings = await settingsApi.get()
    document.documentElement.dataset.theme = settings.appearance
    await router.replace(typeof route.query.redirect === 'string' ? route.query.redirect : '/')
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '登录失败'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="login-page">
    <section class="login-card">
      <div class="brand login-brand"><span class="brand-mark">IH</span><span>Intelligence Hub</span></div>
      <p class="eyebrow">SECURE WORKSPACE</p>
      <h1>欢迎回来</h1>
      <p class="login-intro">使用已分配的手机号和密码进入你的独立工作区。</p>
      <form @submit.prevent="submit">
        <label>手机号<input v-model="phone" type="tel" inputmode="numeric" autocomplete="username" maxlength="11" placeholder="请输入手机号" required /></label>
        <label>密码<input v-model="password" type="password" autocomplete="current-password" minlength="8" placeholder="请输入密码" required /></label>
        <p v-if="error" class="login-error">{{ error }}</p>
        <button class="primary-action" type="submit" :disabled="loading">{{ loading ? '正在登录…' : '登录' }}</button>
      </form>
    </section>
  </main>
</template>
