import { createRouter, createWebHistory } from 'vue-router'

import ChatPage from '@/pages/ChatPage.vue'
import LoginPage from '@/pages/LoginPage.vue'
import SettingsPage from '@/pages/SettingsPage.vue'
import GeneralSettingsPage from '@/pages/settings/GeneralSettingsPage.vue'
import McpSettingsPage from '@/pages/settings/McpSettingsPage.vue'
import MemorySettingsPage from '@/pages/settings/MemorySettingsPage.vue'
import SkillSettingsPage from '@/pages/settings/SkillSettingsPage.vue'
import { useAuth } from '@/features/auth/authStore'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: LoginPage, meta: { public: true } },
    { path: '/', name: 'chat', component: ChatPage },
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
  if (to.meta.public) return auth.user.value ? { name: 'chat' } : true
  if (!auth.user.value) return { name: 'login', query: { redirect: to.fullPath } }
  return true
})

export default router
