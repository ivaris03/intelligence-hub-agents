import { createRouter, createWebHistory } from 'vue-router'

import ChatPage from '@/pages/ChatPage.vue'
import LoginPage from '@/pages/LoginPage.vue'
import SettingsPage from '@/pages/SettingsPage.vue'
import GeneralSettingsPage from '@/pages/settings/GeneralSettingsPage.vue'
import McpSettingsPage from '@/pages/settings/McpSettingsPage.vue'
import MemorySettingsPage from '@/pages/settings/MemorySettingsPage.vue'
import SkillSettingsPage from '@/pages/settings/SkillSettingsPage.vue'
import AdminPage from '@/pages/AdminPage.vue'
import { useAuth } from '@/features/auth/authStore'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: LoginPage, meta: { public: true } },
    { path: '/admin/login', name: 'admin-login', component: LoginPage, meta: { public: true, adminLogin: true } },
    { path: '/', name: 'chat', component: ChatPage },
    { path: '/admin', name: 'admin', component: AdminPage, meta: { admin: true } },
    {
      path: '/settings',
      component: SettingsPage,
      children: [
        { path: '', redirect: { name: 'settings-general' } },
        { path: 'general', name: 'settings-general', component: GeneralSettingsPage },
        { path: 'mcp', name: 'settings-mcp', component: McpSettingsPage },
        { path: 'skill', name: 'settings-skill', component: SkillSettingsPage },
        { path: 'memory', name: 'settings-memory', component: MemorySettingsPage },
      ],
    },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuth()
  if (!auth.initialized.value) await auth.restore()
  if (to.meta.public) {
    if (!auth.user.value) return true
    return auth.user.value.role === 'admin' ? { name: 'admin' } : { name: 'chat' }
  }
  if (!auth.user.value) return { name: to.path.startsWith('/admin') ? 'admin-login' : 'login', query: { redirect: to.fullPath } }
  if (auth.user.value.role === 'admin' && !to.meta.admin) return { name: 'admin' }
  if (to.meta.admin && auth.user.value.role !== 'admin') return { name: 'chat' }
  return true
})

export default router
