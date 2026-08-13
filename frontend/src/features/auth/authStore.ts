import { ref } from 'vue'

import { authApi, type CurrentUser } from '@/lib/api'

const user = ref<CurrentUser | null>(null)
const initialized = ref(false)

async function restore(): Promise<boolean> {
  const token = localStorage.getItem('ih_access_token')
  if (!token) {
    user.value = null
    initialized.value = true
    return false
  }
  try {
    user.value = await authApi.me()
    return true
  } catch {
    localStorage.removeItem('ih_access_token')
    user.value = null
    return false
  } finally {
    initialized.value = true
  }
}

async function login(phone: string, password: string): Promise<void> {
  const session = await authApi.login(phone, password)
  localStorage.setItem('ih_access_token', session.access_token)
  user.value = session.user
  initialized.value = true
}

async function logout(): Promise<void> {
  try {
    await authApi.logout()
  } catch {
    // Local logout remains effective even if the server cannot be reached.
  }
  localStorage.removeItem('ih_access_token')
  user.value = null
}

export function useAuth() {
  return {
    user,
    initialized,
    restore,
    login,
    logout,
  }
}
