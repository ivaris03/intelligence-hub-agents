<script setup lang="ts">
import { computed, ref } from 'vue'

import type { FileRecord, Skill, ThinkingEffort } from '@/lib/api'

const props = defineProps<{
  modelValue: string
  streaming: boolean
  files: FileRecord[]
  selectedFileIds: string[]
  skills: Skill[]
  selectedSkillId: string
  modelName: string
  thinkingEffort: ThinkingEffort
  uploadProgress: Record<string, number>
}>()
const emit = defineEmits<{
  'update:modelValue': [value: string]
  'update:selectedSkillId': [value: string]
  'update:thinkingEffort': [value: ThinkingEffort]
  send: [value: string]
  stop: []
  addFiles: [files: FileList]
  toggleFile: [id: string]
}>()
const fileInput = ref<HTMLInputElement | null>(null)
const showFiles = ref(false)
const content = computed({
  get: () => props.modelValue,
  set: (value: string) => emit('update:modelValue', value),
})
const selectedFiles = computed(() => props.files.filter((file) => props.selectedFileIds.includes(file.id)))

function submit() {
  if (!content.value.trim() || props.streaming) return
  emit('send', content.value)
  content.value = ''
  showFiles.value = false
}

function chooseFiles(event: Event) {
  const input = event.target as HTMLInputElement
  if (input.files?.length) emit('addFiles', input.files)
  input.value = ''
}

function readableSize(bytes: number) {
  if (bytes < 1024 * 1024) return `${Math.ceil(bytes / 1024)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}
</script>

<template>
  <div class="composer-shell">
    <div v-if="selectedFiles.length || Object.keys(uploadProgress).length" class="attachment-strip">
      <span v-for="file in selectedFiles" :key="file.id" class="attachment-chip">
        {{ file.kind === 'image' ? '▧' : '▤' }} {{ file.name }}
        <button type="button" aria-label="移除文件" @click="$emit('toggleFile', file.id)">×</button>
      </span>
      <span v-for="(progress, name) in uploadProgress" :key="name" class="attachment-chip uploading">
        {{ name }} · {{ progress }}%
      </span>
    </div>
    <form class="composer" @submit.prevent="submit">
      <textarea
        v-model="content"
        aria-label="消息"
        rows="1"
        placeholder="输入消息，或描述想完成的工作…"
        @keydown.enter.exact.prevent="submit"
      ></textarea>
      <div v-if="showFiles" class="file-popover">
        <div class="popover-head"><b>选择已上传文件</b><small>本轮最多 3 个</small></div>
        <button
          v-for="file in files"
          :key="file.id"
          type="button"
          class="file-option"
          :class="{ selected: selectedFileIds.includes(file.id) }"
          @click="$emit('toggleFile', file.id)"
        >
          <span>{{ file.kind === 'image' ? '▧' : '▤' }}</span>
          <span><b>{{ file.name }}</b><small>{{ readableSize(file.size) }}</small></span>
          <span>{{ selectedFileIds.includes(file.id) ? '✓' : '' }}</span>
        </button>
        <p v-if="!files.length">尚未上传文件</p>
        <button type="button" class="upload-new" @click="fileInput?.click()">＋ 上传新文件</button>
      </div>
      <div class="composer-actions">
        <div class="composer-left-actions">
          <input
            ref="fileInput"
            class="visually-hidden"
            type="file"
            multiple
            accept=".txt,.md,.pdf,.docx,.png,.jpg,.jpeg,.webp"
            @change="chooseFiles"
          />
          <button type="button" class="icon-button" title="添加文件" @click="showFiles = !showFiles">＋</button>
          <select
            class="skill-select"
            :value="selectedSkillId"
            aria-label="选择 Skill"
            @change="$emit('update:selectedSkillId', ($event.target as HTMLSelectElement).value)"
          >
            <option value="">@ Skill · 自动</option>
            <option v-for="skill in skills" :key="skill.id" :value="skill.id">@{{ skill.name }}</option>
          </select>
        </div>
        <div class="composer-submit-actions">
          <label class="model-effort-control" title="当前模型和本轮思考强度">
            <span>{{ modelName }}</span>
            <select
              :value="thinkingEffort"
              :disabled="streaming"
              aria-label="选择思考强度"
              @change="$emit('update:thinkingEffort', ($event.target as HTMLSelectElement).value as ThinkingEffort)"
            >
              <option value="none">无</option>
              <option value="low">低</option>
              <option value="medium">中</option>
              <option value="high">高</option>
            </select>
          </label>
          <button v-if="streaming" type="button" class="send-button stop" title="停止" @click="$emit('stop')">■</button>
          <button v-else type="submit" class="send-button" :disabled="!content.trim()" title="发送">↑</button>
        </div>
      </div>
    </form>
    <p class="composer-hint">AI 可能会犯错，请核对重要信息。上传内容仅用于当前本地工作区。</p>
  </div>
</template>
