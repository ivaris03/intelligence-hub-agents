import { createRouter, createWebHistory } from 'vue-router'

import ChatPage from '@/pages/ChatPage.vue'
import SettingsPage from '@/pages/SettingsPage.vue'
import GeneralSettingsPage from '@/pages/settings/GeneralSettingsPage.vue'
import McpSettingsPage from '@/pages/settings/McpSettingsPage.vue'
import MemorySettingsPage from '@/pages/settings/MemorySettingsPage.vue'
import SkillSettingsPage from '@/pages/settings/SkillSettingsPage.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [
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
