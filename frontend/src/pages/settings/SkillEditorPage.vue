<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { skillsApi } from '@/lib/api'

const route = useRoute()
const router = useRouter()
const error = ref('')
const loading = ref(Boolean(route.params.skillId))
const skillId = typeof route.params.skillId === 'string' ? route.params.skillId : null
const skillForm = reactive({ name: '', description: '', instructions: '', enabled: true })
const isEditing = Boolean(skillId)

onMounted(async () => {
  if (!skillId) return

  try {
    const skill = (await skillsApi.list()).find((item) => item.id === skillId)
    if (!skill) {
      await router.replace({ name: 'settings-skill' })
      return
    }
    Object.assign(skillForm, {
      name: skill.name,
      description: skill.description,
      instructions: skill.instructions,
      enabled: skill.enabled,
    })
  } catch (cause) {
    report(cause)
  } finally {
    loading.value = false
  }
})

function report(cause: unknown) {
  error.value = cause instanceof Error ? cause.message : '操作失败'
}

async function saveSkill() {
  if (!skillForm.name.trim() || !skillForm.instructions.trim()) return

  try {
    if (skillId) await skillsApi.update(skillId, skillForm)
    else await skillsApi.create(skillForm)
    await router.push({ name: 'settings-skill' })
  } catch (cause) {
    report(cause)
  }
}
</script>

<template>
  <div v-if="error" class="global-error"><span>{{ error }}</span><button @click="error = ''">×</button></div>
  <p v-if="loading" class="loading-state"><span></span>读取 Skill…</p>

  <section v-else class="settings-section skill-editor-page">
    <RouterLink class="back-link editor-back-link" :to="{ name: 'settings-skill' }">← 返回 Skill</RouterLink>
    <header><div><span class="section-kicker">SKILL</span><h2>{{ isEditing ? '编辑 Skill' : '新建 Skill' }}</h2><p>定义任务的目标、风格和输出格式。</p></div></header>
    <form class="editor-card" @submit.prevent="saveSkill">
      <label>名称<input v-model="skillForm.name" maxlength="80" required placeholder="例如：技术写作" /></label>
      <label>描述<input v-model="skillForm.description" maxlength="500" placeholder="系统据此进行自动选择" /></label>
      <label>指令<textarea v-model="skillForm.instructions" rows="10" maxlength="20000" required placeholder="说明任务目标、风格和输出格式…"></textarea></label>
      <label class="inline-check"><input v-model="skillForm.enabled" type="checkbox" /> {{ isEditing ? '启用此 Skill' : '创建后启用' }}</label>
      <div class="editor-actions"><RouterLink class="editor-cancel-link" :to="{ name: 'settings-skill' }">取消</RouterLink><button class="primary-action" type="submit">{{ isEditing ? '保存修改' : '创建 Skill' }}</button></div>
    </form>
  </section>
</template>
