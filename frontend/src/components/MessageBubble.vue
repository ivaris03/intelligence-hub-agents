<script setup lang="ts">
import { computed, ref } from 'vue'

import type { Message } from '@/features/chat/chatStore'
import { renderMarkdown } from '@/lib/markdown'

type SourceItem = {
  kind: 'file' | 'image' | 'web'
  name?: string
  locator?: string
  title?: string
  url?: string
  snippet?: string
}

const props = defineProps<{ message: Message }>()
defineEmits<{ followUp: [text: string]; regenerate: [message: Message] }>()
const copied = ref(false)
const html = computed(() => renderMarkdown(props.message.content))
const sources = computed<SourceItem[]>(() => {
  const part = props.message.parts.find((item) => item.type === 'sources')
  return (part?.data.items as SourceItem[] | undefined) ?? []
})

async function copy() {
  await navigator.clipboard.writeText(props.message.content)
  copied.value = true
  window.setTimeout(() => (copied.value = false), 1200)
}
</script>

<template>
  <article class="message" :class="message.role">
    <div v-if="message.role === 'assistant'" class="assistant-icon">✦</div>
    <div class="message-body">
      <div v-if="message.files.length" class="message-files">
        <span v-for="file in message.files" :key="file.id">{{ file.kind === 'image' ? '▧' : '▤' }} {{ file.name }}</span>
      </div>
      <span v-if="message.skill" class="skill-badge">@{{ message.skill.name }}</span>
      <details v-if="message.reasoning" :open="message.status === 'streaming'" class="reasoning">
        <summary>思考过程</summary>
        <p>{{ message.reasoning }}</p>
      </details>
      <div v-if="message.tool_calls.length" class="tool-stack">
        <details v-for="tool in message.tool_calls" :key="tool.id" class="tool-card">
          <summary>
            <span class="tool-status" :class="tool.status"></span>
            <b>{{ tool.tool_name }}</b>
            <small>{{ tool.status }}<template v-if="tool.duration_ms"> · {{ tool.duration_ms }} ms</template></small>
          </summary>
          <dl>
            <dt>参数摘要</dt><dd>{{ tool.input_summary || '无' }}</dd>
            <dt>结果摘要</dt><dd>{{ tool.output_summary || '执行中…' }}</dd>
          </dl>
        </details>
      </div>
      <div v-if="message.role === 'assistant'" class="markdown" v-html="html"></div>
      <p v-else>{{ message.content }}</p>
      <span v-if="message.status === 'streaming'" class="typing-dot"></span>

      <section v-if="sources.length" class="sources-block">
        <h4>来源</h4>
        <ol>
          <li v-for="(source, index) in sources" :key="`${source.url ?? source.name}-${index}`">
            <a v-if="source.url" :href="source.url" target="_blank" rel="noopener noreferrer">
              {{ source.title || source.url }} ↗
            </a>
            <span v-else>{{ source.name }} · {{ source.locator }}</span>
            <small v-if="source.snippet">{{ source.snippet }}</small>
          </li>
        </ol>
      </section>

      <button
        v-if="message.role === 'assistant' && message.status === 'completed' && message.follow_up"
        type="button"
        class="follow-up"
        @click="$emit('followUp', message.follow_up)"
      >
        <span>继续探索</span>{{ message.follow_up }} <b>→</b>
      </button>

      <small v-if="message.status === 'cancelled'" class="status-note">已停止生成</small>
      <small v-if="message.status === 'failed'" class="status-note error">{{ message.error || '生成失败' }}</small>
      <div v-if="message.role === 'assistant' && message.status !== 'streaming'" class="message-actions">
        <button type="button" @click="copy">{{ copied ? '已复制' : '复制' }}</button>
        <button type="button" @click="$emit('regenerate', message)">重新生成</button>
      </div>
    </div>
  </article>
</template>
