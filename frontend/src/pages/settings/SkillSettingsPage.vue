<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { skillsApi, type Skill } from '@/lib/api'

const skills = ref<Skill[]>([])
const loading = ref(true)
const error = ref('')
const pendingSkillDeleteId = ref<string | null>(null)

onMounted(async () => {
  try {
    skills.value = await skillsApi.list()
  } catch (cause) {
    report(cause)
  } finally {
    loading.value = false
  }
})

function report(cause: unknown) {
  error.value = cause instanceof Error ? cause.message : '操作失败'
}

async function toggleSkill(skill: Skill) {
  try {
    const updated = await skillsApi.update(skill.id, { enabled: !skill.enabled })
    const index = skills.value.findIndex((item) => item.id === skill.id)
    if (index >= 0) skills.value[index] = updated
  } catch (cause) {
    report(cause)
  }
}

async function removeSkill(skill: Skill) {
  try {
    await skillsApi.remove(skill.id)
    skills.value = skills.value.filter((item) => item.id !== skill.id)
    pendingSkillDeleteId.value = null
  } catch (cause) {
    report(cause)
  }
}
</script>

<template>
  <div v-if="error" class="global-error"><span>{{ error }}</span><button @click="error = ''">×</button></div>
  <p v-if="loading" class="loading-state"><span></span>读取设置…</p>

  <section v-if="!loading" class="settings-section">
    <header>
      <div><span class="section-kicker">SKILL</span><h2>任务技能</h2><p>选择器支持显式调用；未选择时可自动匹配，@ 不会触发调用。历史消息保存不可变快照。</p></div>
      <div class="section-header-actions"><span>{{ skills.length }} 个</span><RouterLink class="primary-action create-skill-link" :to="{ name: 'settings-skill-create' }">新建 Skill</RouterLink></div>
    </header>
    <div class="manage-list">
      <article v-for="skill in skills" :key="skill.id" class="manage-item">
        <div><div class="item-title"><b>{{ skill.name }}</b><span :class="{ off: !skill.enabled }">{{ skill.enabled ? '已启用' : '已停用' }}</span></div><p>{{ skill.description || '暂无描述' }}</p></div>
        <div class="item-actions">
          <RouterLink class="item-action-link" :to="{ name: 'settings-skill-edit', params: { skillId: skill.id } }">编辑</RouterLink><button @click="toggleSkill(skill)">{{ skill.enabled ? '停用' : '启用' }}</button>
          <button v-if="pendingSkillDeleteId !== skill.id" class="danger" @click="pendingSkillDeleteId = skill.id">删除</button>
          <button v-else class="danger" @click="removeSkill(skill)">确认删除</button>
          <button v-if="pendingSkillDeleteId === skill.id" @click="pendingSkillDeleteId = null">取消</button>
        </div>
      </article>
      <p v-if="!skills.length" class="manage-empty">还没有 Skill。创建后可在输入区选择或输入 @名称。</p>
    </div>
  </section>
</template>
