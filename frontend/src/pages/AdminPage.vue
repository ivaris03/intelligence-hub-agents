<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { adminUsersApi, type CurrentUser } from '@/lib/api'
import { useAuth } from '@/features/auth/authStore'
const auth = useAuth(); const router = useRouter(); const users = ref<CurrentUser[]>([]); const query = ref(''); const loading = ref(true); const error = ref(''); const saving = ref(false)
const form = ref({ phone: '', display_name: '', password: '', role: 'member' as 'admin' | 'member' })
const stats = computed(() => ({ total: users.value.length, active: users.value.filter((u) => u.is_active).length, admins: users.value.filter((u) => u.role === 'admin').length }))
async function load() { loading.value = true; try { users.value = await adminUsersApi.list(query.value) } catch (e) { error.value = e instanceof Error ? e.message : '读取用户失败' } finally { loading.value = false } }
async function createUser() { saving.value = true; try { const created = await adminUsersApi.create(form.value); users.value.unshift(created); form.value = { phone: '', display_name: '', password: '', role: 'member' } } catch (e) { error.value = e instanceof Error ? e.message : '创建用户失败' } finally { saving.value = false } }
async function updateUser(user: CurrentUser, payload: Partial<{ role: 'admin' | 'member'; is_active: boolean }>) { try { const updated = await adminUsersApi.update(user.id, payload); const index = users.value.findIndex((item) => item.id === user.id); if (index >= 0) users.value[index] = updated; if (auth.user.value?.id === updated.id) auth.user.value = updated } catch (e) { error.value = e instanceof Error ? e.message : '更新用户失败' } }
async function signOut() { await auth.logout(); await router.replace('/login') }
onMounted(load)
</script>
<template>
  <div class="settings-layout admin-layout"><aside class="settings-nav"><h2>管理端</h2><RouterLink to="/admin" class="router-link-active">用户与权限</RouterLink><div class="admin-profile"><span>{{ auth.user.value?.display_name.slice(0, 1) }}</span><div><b>{{ auth.user.value?.display_name }}</b><small>管理员</small></div><button type="button" @click="signOut">退出登录</button></div></aside>
    <main class="settings-content"><p class="eyebrow">ADMIN CONSOLE</p><h1>工作区管理</h1><div v-if="error" class="global-error admin-error"><span>{{ error }}</span><button @click="error = ''">×</button></div>
      <section class="admin-stats"><div><small>全部用户</small><b>{{ stats.total }}</b></div><div><small>已启用</small><b>{{ stats.active }}</b></div><div><small>管理员</small><b>{{ stats.admins }}</b></div></section>
      <section class="settings-section"><header><div><span class="section-kicker">USERS</span><h2>用户目录</h2><p>管理账号状态和工作区权限。</p></div><div class="admin-search"><input v-model="query" placeholder="搜索姓名或手机号" @keyup.enter="load" /><button @click="load">搜索</button></div></header><p v-if="loading" class="loading-state"><span></span>读取用户…</p><div v-else class="manage-list"><article v-for="user in users" :key="user.id" class="manage-item admin-user"><div><div class="item-title"><b>{{ user.display_name }}</b><span :class="{ off: !user.is_active }">{{ user.is_active ? '已启用' : '已停用' }}</span></div><p>{{ user.phone }} · {{ user.role === 'admin' ? '管理员' : '成员' }}</p></div><div class="item-actions"><button @click="updateUser(user, { is_active: !user.is_active })">{{ user.is_active ? '停用' : '启用' }}</button><button @click="updateUser(user, { role: user.role === 'admin' ? 'member' : 'admin' })">{{ user.role === 'admin' ? '设为成员' : '设为管理员' }}</button></div></article><p v-if="!users.length" class="manage-empty">没有匹配的用户。</p></div></section>
      <form class="editor-card admin-create" @submit.prevent="createUser"><header><div><span class="section-kicker">INVITE</span><h3>新建用户</h3></div></header><div class="admin-form-grid"><label>姓名<input v-model="form.display_name" required maxlength="80" /></label><label>手机号<input v-model="form.phone" required pattern="1[3-9][0-9]{9}" maxlength="11" /></label><label>初始密码<input v-model="form.password" required minlength="8" type="password" /></label><label>角色<select v-model="form.role"><option value="member">成员</option><option value="admin">管理员</option></select></label></div><button class="primary-action" :disabled="saving">{{ saving ? '创建中…' : '创建账号' }}</button></form>
    </main></div>
</template>
