<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { skillsApi, type Skill } from '@/lib/api'

const skills = ref<Skill[]>([])
const loading = ref(true)
const error = ref('')
const editingSkillId = ref<string | null>(null)
const pendingSkillDeleteId = ref<string | null>(null)
const skillForm = reactive({ name: '', description: '', instructions: '', enabled: true })

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

function resetSkillForm() {
  editingSkillId.value = null
  Object.assign(skillForm, { name: '', description: '', instructions: '', enabled: true })
}

function editSkill(skill: Skill) {
  editingSkillId.value = skill.id
  Object.assign(skillForm, {
    name: skill.name,
    description: skill.description,
    instructions: skill.instructions,
    enabled: skill.enabled,
  })
  document.querySelector('#skill-editor')?.scrollIntoView({ behavior: 'smooth' })
}

async function saveSkill() {
  if (!skillForm.name.trim() || !skillForm.instructions.trim()) return
  try {
    if (editingSkillId.value) {
      const updated = await skillsApi.update(editingSkillId.value, skillForm)
      const index = skills.value.findIndex((item) => item.id === updated.id)
      if (index >= 0) skills.value[index] = updated
    } else {
      skills.value.unshift(await skillsApi.create(skillForm))
    }
    resetSkillForm()
  } catch (cause) {
    report(cause)
  }
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
    if (editingSkillId.value === skill.id) resetSkillForm()
  } catch (cause) {
    report(cause)
  }
}
</script>

<template>
  <div v-if="error" class="global-error"><span>{{ error }}</span><button @click="error = ''">×</button></div>
  <p v-if="loading" class="loading-state"><span></span>读取设置…</p>

  <section v-if="!loading" class="settings-section">
    <header><div><span class="section-kicker">SKILL</span><h2>任务技能</h2><p>显式 @ 选择优先；历史消息保存不可变快照。</p></div><span>{{ skills.length }} 个</span></header>
    <div class="manage-list">
      <article v-for="skill in skills" :key="skill.id" class="manage-item">
        <div><div class="item-title"><b>@{{ skill.name }}</b><span :class="{ off: !skill.enabled }">{{ skill.enabled ? '已启用' : '已停用' }}</span></div><p>{{ skill.description || '暂无描述' }}</p></div>
        <div class="item-actions">
          <button @click="editSkill(skill)">编辑</button><button @click="toggleSkill(skill)">{{ skill.enabled ? '停用' : '启用' }}</button>
          <button v-if="pendingSkillDeleteId !== skill.id" class="danger" @click="pendingSkillDeleteId = skill.id">删除</button>
          <button v-else class="danger" @click="removeSkill(skill)">确认删除</button>
          <button v-if="pendingSkillDeleteId === skill.id" @click="pendingSkillDeleteId = null">取消</button>
        </div>
      </article>
      <p v-if="!skills.length" class="manage-empty">还没有 Skill。创建后可在输入区选择或输入 @名称。</p>
    </div>
    <form id="skill-editor" class="editor-card" @submit.prevent="saveSkill">
      <header><h3>{{ editingSkillId ? '编辑 Skill' : '新建 Skill' }}</h3><button v-if="editingSkillId" type="button" @click="resetSkillForm">取消编辑</button></header>
      <label>名称<input v-model="skillForm.name" maxlength="80" required placeholder="例如：技术写作" /></label>
      <label>描述<input v-model="skillForm.description" maxlength="500" placeholder="系统据此进行自动选择" /></label>
      <label>指令<textarea v-model="skillForm.instructions" rows="7" maxlength="20000" required placeholder="说明任务目标、风格和输出格式…"></textarea></label>
      <label class="inline-check"><input v-model="skillForm.enabled" type="checkbox" /> 创建后启用</label>
      <button class="primary-action" type="submit">{{ editingSkillId ? '保存修改' : '创建 Skill' }}</button>
    </form>
  </section>
</template>
