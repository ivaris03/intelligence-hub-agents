<script setup lang="ts">
import type { AgentRun } from '@/features/chat/chatStore'
import { renderMarkdown } from '@/lib/markdown'

defineProps<{ run: AgentRun }>()
defineEmits<{ command: [run: AgentRun, action: 'confirm' | 'cancel' | 'retry' | 'resume'] }>()

const agentNames = { image: '图片 Agent', slides: '演示 Agent', research: '研究 Agent' }
const stageNames: Record<string, string> = {
  queued: '等待开始',
  preparing: '读取参考资料',
  brief: '整理图片需求',
  generating: '生成图片',
  routing: '识别演示意图',
  outlining: '生成大纲',
  awaiting_confirmation: '等待确认',
  content: '生成页面内容',
  rendering: '渲染 PPTX',
  planning: '研究规划',
  researching: '搜索与证据整理',
  validating: '校验结果',
  saving: '保存产物',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
}

function outline(run: AgentRun) {
  return run.public_state.outline as { title?: string; slides?: string[] } | undefined
}

function modification(run: AgentRun) {
  return run.public_state.modification_plan as { target_slides?: number[]; instruction?: string } | undefined
}

function artifactTitles(metadata: Record<string, unknown>) {
  return (metadata.titles as string[] | undefined) ?? []
}
</script>

<template>
  <article class="run-block">
    <div class="run-request">
      <span class="run-mode">WORK · {{ agentNames[run.agent_type] }}</span>
      <p>{{ run.input }}</p>
      <div v-if="run.files.length" class="message-files">
        <span v-for="file in run.files" :key="file.id">{{ file.kind === 'image' ? '▧' : '▤' }} {{ file.name }}</span>
      </div>
    </div>
    <div class="run-card" :class="run.status">
      <header>
        <div><span class="agent-glyph">✦</span><div><b>{{ agentNames[run.agent_type] }}</b><small>{{ run.intent }} · {{ run.id.startsWith('pending-') ? '正在创建' : run.id.slice(0, 8) }}</small></div></div>
        <span class="run-status">{{ stageNames[run.stage] || run.stage }}</span>
      </header>
      <div class="run-progress"><span :class="{ done: run.status === 'completed' }"></span></div>
      <div class="run-context">
        <span v-if="run.skill">@{{ run.skill.name }}</span>
        <span v-if="run.public_state.memory_summary">用户记忆摘要</span>
        <span v-if="run.public_state.framework">{{ run.public_state.framework }}</span>
      </div>

      <details v-if="run.events.length" class="run-events" :open="run.status === 'running'">
        <summary>执行过程 · {{ run.events.length }} 个事件</summary>
        <ol>
          <li v-for="event in run.events" :key="`${event.seq}-${event.type}`">
            <span class="event-dot" :class="event.type.replace('.', '-')"></span>
            <div>
              <b>{{ event.type === 'run.stage' ? String(event.payload.label || event.payload.stage) : event.type }}</b>
              <small v-if="event.type.startsWith('tool.')">
                {{ event.payload.name }}
                <template v-if="event.payload.duration_ms"> · {{ event.payload.duration_ms }} ms</template>
              </small>
              <details v-if="event.type.startsWith('tool.')" class="event-detail">
                <summary>查看安全摘要</summary>
                <p>{{ event.payload.input_summary || event.payload.output_summary }}</p>
              </details>
            </div>
          </li>
        </ol>
      </details>

      <section v-if="outline(run)" class="outline-card">
        <span class="section-kicker">演示大纲</span>
        <h3>{{ outline(run)?.title }}</h3>
        <ol><li v-for="slide in outline(run)?.slides" :key="slide">{{ slide }}</li></ol>
      </section>
      <section v-if="modification(run)" class="outline-card">
        <span class="section-kicker">修改计划</span>
        <h3>目标页面：{{ modification(run)?.target_slides?.join('、') }}</h3>
        <p>{{ modification(run)?.instruction }}</p>
      </section>

      <div v-if="run.status === 'awaiting_confirmation'" class="run-confirmation">
        <p>确认后才会生成新的 PPTX；原版本不会被覆盖。</p>
        <button type="button" class="primary-action" @click="$emit('command', run, 'confirm')">确认并继续</button>
        <button type="button" @click="$emit('command', run, 'cancel')">取消</button>
      </div>

      <section v-if="run.artifacts.length" class="artifact-grid">
        <article v-for="artifact in run.artifacts" :key="artifact.id" class="artifact-card">
          <img v-if="artifact.type === 'image'" :src="artifact.download_url" :alt="artifact.name" />
          <div v-else class="artifact-file-icon">{{ artifact.type === 'pptx' ? 'P' : 'MD' }}</div>
          <div class="artifact-copy">
            <span>{{ artifact.type.toUpperCase() }} · v{{ artifact.version }}</span>
            <b>{{ artifact.name }}</b>
            <small>{{ Math.ceil(artifact.size / 1024) }} KB</small>
            <ol v-if="artifact.type === 'pptx' && artifactTitles(artifact.metadata).length" class="slide-preview-list">
              <li v-for="title in artifactTitles(artifact.metadata).slice(0, 5)" :key="title">{{ title }}</li>
            </ol>
            <a :href="artifact.download_url">下载产物 ↓</a>
          </div>
        </article>
      </section>

      <div v-if="run.agent_type === 'research' && run.answer" class="markdown research-report" v-html="renderMarkdown(run.answer)"></div>
      <p v-else-if="run.answer" class="run-answer">{{ run.answer }}</p>
      <p v-if="run.error" class="run-error">{{ run.error }}</p>
      <div v-if="run.status === 'failed' || run.status === 'cancelled'" class="run-retry">
        <button type="button" class="primary-action" @click="$emit('command', run, run.agent_type === 'slides' ? 'resume' : 'retry')">
          {{ run.agent_type === 'slides' ? '从最近阶段恢复' : '重试' }}
        </button>
      </div>
      <button v-if="run.status === 'running'" type="button" class="cancel-run" @click="$emit('command', run, 'cancel')">停止运行</button>
    </div>
  </article>
</template>
