<script setup lang="ts">
import { computed } from 'vue'

import type { Message } from '@/features/chat/chatStore'
import { renderMarkdown } from '@/lib/markdown'

const props = defineProps<{ message: Message }>()
const html = computed(() => renderMarkdown(props.message.content))
</script>

<template>
  <article class="message" :class="message.role">
    <div v-if="message.role === 'assistant'" class="assistant-icon">✦</div>
    <div class="message-body">
      <details v-if="message.reasoning" :open="message.status === 'streaming'" class="reasoning">
        <summary>思考过程</summary>
        <p>{{ message.reasoning }}</p>
      </details>
      <div v-if="message.role === 'assistant'" class="markdown" v-html="html"></div>
      <p v-else>{{ message.content }}</p>
      <span v-if="message.status === 'streaming'" class="typing-dot"></span>
      <small v-if="message.status === 'cancelled'" class="status-note">已停止生成</small>
      <small v-if="message.status === 'failed'" class="status-note error">生成失败</small>
    </div>
  </article>
</template>
