<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import {
  memoriesApi,
  settingsApi,
  skillsApi,
  type AppSettings,
  type MemoryRecord,
  type Skill,
} from '@/lib/api'

const settings = ref<AppSettings | null>(null)
const skills = ref<Skill[]>([])
const memories = ref<MemoryRecord[]>([])
const loading = ref(true)
const error = ref('')
const editingSkillId = ref<string | null>(null)
const pendingSkillDeleteId = ref<string | null>(null)
const editingMemoryId = ref<string | null>(null)
const memoryEditContent = ref('')
const pendingMemoryDeleteId = ref<string | null>(null)
const clearMemoriesArmed = ref(false)
const skillForm = reactive({ name: '', description: '', instructions: '', enabled: true })
const memoryContent = ref('')

onMounted(async () => {
  try {
    ;[settings.value, skills.value, memories.value] = await Promise.all([
      settingsApi.get(),
      skillsApi.list(),
      memoriesApi.list(),
    ])
    applyTheme(settings.value.appearance)
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

async function addMemory() {
  if (!memoryContent.value.trim()) return
  try {
    memories.value.unshift(await memoriesApi.create(memoryContent.value.trim()))
    memoryContent.value = ''
  } catch (cause) {
    report(cause)
  }
}

function editMemory(memory: MemoryRecord) {
  editingMemoryId.value = memory.id
  memoryEditContent.value = memory.content
}

async function saveMemory(memory: MemoryRecord) {
  const content = memoryEditContent.value.trim()
  if (!content) return
  try {
    const updated = await memoriesApi.update(memory.id, content)
    const index = memories.value.findIndex((item) => item.id === memory.id)
    if (index >= 0) memories.value[index] = updated
    editingMemoryId.value = null
  } catch (cause) {
    report(cause)
  }
}

async function removeMemory(memory: MemoryRecord) {
  try {
    await memoriesApi.remove(memory.id)
    memories.value = memories.value.filter((item) => item.id !== memory.id)
    pendingMemoryDeleteId.value = null
  } catch (cause) {
    report(cause)
  }
}

async function clearMemories() {
  try {
    await memoriesApi.clear()
    memories.value = []
    clearMemoriesArmed.value = false
  } catch (cause) {
    report(cause)
  }
}

async function updateSetting(payload: Partial<Pick<AppSettings, 'memory_enabled' | 'web_search_enabled' | 'appearance'>>) {
  try {
    settings.value = await settingsApi.update(payload)
    applyTheme(settings.value.appearance)
  } catch (cause) {
    report(cause)
  }
}

function applyTheme(theme: AppSettings['appearance']) {
  document.documentElement.dataset.theme = theme
}

function sourceLabel(memory: MemoryRecord) {
  return { manual: '设置页添加', explicit: '对话指令', automatic: '闲置提炼' }[memory.source]
}
</script>

<template>
  <div class="settings-layout">
    <aside class="settings-nav">
      <RouterLink to="/" class="back-link">← 返回对话</RouterLink>
      <h2>设置</h2>
      <a class="active" href="#general">服务与外观</a>
      <a href="#skill">Skill</a>
      <a href="#memory">Memory</a>
    </aside>
    <main class="settings-content">
      <p class="eyebrow">SETTINGS</p>
      <h1>让 Hub 更适合你</h1>
      <div v-if="error" class="global-error"><span>{{ error }}</span><button @click="error = ''">×</button></div>
      <p v-if="loading" class="loading-state"><span></span>读取设置…</p>

      <template v-if="settings">
        <section id="general" class="settings-section">
          <header><div><span class="section-kicker">GENERAL</span><h2>服务与外观</h2></div></header>
          <div class="settings-card">
            <div><h3>模型服务</h3><p>密钥仅从服务端环境变量读取，不会发送到浏览器。</p></div>
            <span class="status-badge" :class="{ ready: settings.model_ready }">{{ settings.model_ready ? 'Qwen 已连接' : '本地演示模式' }}</span>
          </div>
          <div class="settings-card">
            <div><h3>联网搜索</h3><p>只在消息明确要求搜索时调用 Tavily MCP。</p></div>
            <div class="setting-control"><small>{{ settings.tavily_ready ? 'Tavily 已配置' : '未配置密钥' }}</small><label class="switch"><input :checked="settings.web_search_enabled" type="checkbox" aria-label="启用联网搜索" @change="updateSetting({ web_search_enabled: !settings?.web_search_enabled })" /><span></span></label></div>
          </div>
          <div class="settings-card">
            <div><h3>外观</h3><p>选择系统、浅色或深色主题。</p></div>
            <select :value="settings.appearance" aria-label="外观主题" @change="updateSetting({ appearance: ($event.target as HTMLSelectElement).value as AppSettings['appearance'] })">
              <option value="system">跟随系统</option><option value="light">浅色</option><option value="dark">深色</option>
            </select>
          </div>
        </section>

        <section id="skill" class="settings-section">
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

        <section id="memory" class="settings-section">
          <header><div><span class="section-kicker">MEMORY</span><h2>长期记忆</h2><p>关闭后不提炼、不写入，也不注入上下文；已有内容保留。</p></div><label class="switch"><input :checked="settings.memory_enabled" type="checkbox" aria-label="启用 Memory" @change="updateSetting({ memory_enabled: !settings?.memory_enabled })" /><span></span></label></header>
          <form class="memory-add" @submit.prevent="addMemory"><input v-model="memoryContent" :disabled="!settings.memory_enabled" maxlength="500" placeholder="添加稳定的偏好或背景信息" /><button class="primary-action" :disabled="!settings.memory_enabled">添加</button></form>
          <div class="manage-list memory-list">
            <article v-for="memory in memories" :key="memory.id" class="manage-item">
              <div>
                <input
                  v-if="editingMemoryId === memory.id"
                  v-model="memoryEditContent"
                  class="memory-inline-editor"
                  aria-label="Memory 内容"
                  maxlength="500"
                  @keydown.enter.prevent="saveMemory(memory)"
                  @keydown.escape.prevent="editingMemoryId = null"
                />
                <p v-else class="memory-content">{{ memory.content }}</p>
                <small>{{ sourceLabel(memory) }} · {{ new Date(memory.updated_at).toLocaleString() }}</small>
              </div>
              <div v-if="editingMemoryId === memory.id" class="item-actions"><button class="primary-action" @click="saveMemory(memory)">保存</button><button @click="editingMemoryId = null">取消</button></div>
              <div v-else class="item-actions">
                <button @click="editMemory(memory)">编辑</button>
                <button v-if="pendingMemoryDeleteId !== memory.id" class="danger" @click="pendingMemoryDeleteId = memory.id">删除</button>
                <button v-else class="danger" @click="removeMemory(memory)">确认删除</button>
                <button v-if="pendingMemoryDeleteId === memory.id" @click="pendingMemoryDeleteId = null">取消</button>
              </div>
            </article>
            <p v-if="!memories.length" class="manage-empty">暂无 Memory。也可以在对话中说“请记住…”来添加。</p>
          </div>
          <div v-if="memories.length" class="clear-memory-actions">
            <button v-if="!clearMemoriesArmed" class="danger-outline" @click="clearMemoriesArmed = true">清空全部 Memory</button>
            <template v-else><button class="danger-outline" @click="clearMemories">确认清空</button><button @click="clearMemoriesArmed = false">取消</button></template>
          </div>
        </section>
      </template>
    </main>
  </div>
</template>
