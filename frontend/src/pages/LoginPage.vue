<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useAuth } from '@/features/auth/authStore'
import { settingsApi } from '@/lib/api'

const auth = useAuth()
const route = useRoute()
const router = useRouter()
const adminLogin = computed(() => route.meta.adminLogin === true)
const phone = ref(adminLogin.value ? '13900000001' : '13700000001')
const password = ref('12345678')
const loading = ref(false)
const error = ref('')

async function submit() {
  error.value = ''
  loading.value = true
  try {
    await auth.login(phone.value.trim(), password.value)
    if (adminLogin.value && auth.user.value?.role !== 'admin') {
      await auth.logout()
      throw new Error('该账号不是管理员，无法进入管理端')
    }
    if (auth.user.value?.role === 'admin') {
      await router.replace('/admin')
    } else {
      const settings = await settingsApi.get()
      document.documentElement.dataset.theme = settings.appearance
      await router.replace(typeof route.query.redirect === 'string' ? route.query.redirect : '/')
    }
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
      <p class="eyebrow">{{ adminLogin ? 'ADMIN CONSOLE' : 'SECURE WORKSPACE' }}</p>
      <h1>{{ adminLogin ? '管理员登录' : '欢迎回来' }}</h1>
      <p class="login-intro">{{ adminLogin ? '仅管理员账号可进入管理端。' : '使用已分配的手机号和密码进入你的独立工作区。' }}</p>
      <form @submit.prevent="submit">
        <label>手机号<input v-model="phone" type="tel" inputmode="numeric" autocomplete="username" maxlength="11" placeholder="请输入手机号" required /></label>
        <label>密码<input v-model="password" type="password" autocomplete="current-password" minlength="8" placeholder="请输入密码" required /></label>
        <p v-if="error" class="login-error">{{ error }}</p>
        <button class="primary-action" type="submit" :disabled="loading">{{ loading ? '正在登录…' : '登录' }}</button>
      </form>
    </section>
  </main>
</template>
