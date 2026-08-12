<script setup lang="ts">
import { ref } from 'vue'

defineProps<{ streaming: boolean }>()
const emit = defineEmits<{ send: [value: string]; stop: [] }>()
const content = ref('')

function submit() {
  if (!content.value.trim()) return
  emit('send', content.value)
  content.value = ''
}
</script>

<template>
  <div class="composer-shell">
    <form class="composer" @submit.prevent="submit">
      <textarea
        v-model="content"
        aria-label="消息"
        rows="1"
        placeholder="输入消息，或描述想完成的工作…"
        @keydown.enter.exact.prevent="submit"
      ></textarea>
      <div class="composer-actions">
        <div>
          <button type="button" class="icon-button" title="添加文件">＋</button>
          <button type="button" class="text-button">@ Skill</button>
        </div>
        <button v-if="streaming" type="button" class="send-button stop" title="停止" @click="$emit('stop')">■</button>
        <button v-else type="submit" class="send-button" :disabled="!content.trim()" title="发送">↑</button>
      </div>
    </form>
    <p class="composer-hint">AI 可能会犯错，请核对重要信息。</p>
  </div>
</template>

