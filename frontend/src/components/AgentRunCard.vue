<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'

import type { AgentRun } from '@/features/chat/chatStore'
import { artifactObjectUrl, downloadArtifact } from '@/lib/api'
import { renderMarkdown } from '@/lib/markdown'

const props = defineProps<{ run: AgentRun }>()
defineEmits<{ command: [run: AgentRun, action: 'confirm' | 'cancel' | 'retry' | 'resume'] }>()

const agentNames = { image: '图片 Agent', slides: 'PPT Agent', research: '研究 Agent' }
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
  topic_drafting: '生成研究主题',
  planning: '制定研究计划',
  executing: '执行研究计划',
  evaluating: '评估研究结果',
  summarizing: '汇总研究报告',
  validating: '校验结果',
  saving: '保存产物',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
}
const previews = ref<Record<string, string>>({})

watch(
  () => props.run.artifacts.map((artifact) => `${artifact.id}:${artifact.download_url}`).join('|'),
  async () => {
    for (const artifact of props.run.artifacts.filter((item) => item.type === 'image')) {
      if (!previews.value[artifact.id]) {
        try {
          previews.value[artifact.id] = await artifactObjectUrl(artifact.download_url)
        } catch {
          // The download action still reports an explicit error if preview loading fails.
        }
      }
    }
  },
  { immediate: true },
)

onBeforeUnmount(() => Object.values(previews.value).forEach(URL.revokeObjectURL))

function outline(run: AgentRun) {
  return run.public_state.outline as { title?: string; slides?: string[] } | undefined
}

function modification(run: AgentRun) {
  return run.public_state.modification_plan as { target_slides?: number[]; instruction?: string } | undefined
}

type ResearchTopic = {
  title?: string
  objective?: string
  scope?: string[]
  key_questions?: string[]
  constraints?: string[]
  deliverable?: string
}

type ResearchCycle = {
  iteration?: number
  plan?: { focus?: string[]; search_queries?: string[] }
  execution?: { summary?: string; findings?: string[]; remaining_gaps?: string[] }
  evaluation?: { sufficient?: boolean; gaps?: string[]; rationale?: string }
}

function researchTopic(run: AgentRun) {
  return run.public_state.research_topic as ResearchTopic | undefined
}

function researchCycles(run: AgentRun) {
  return (run.public_state.research_cycle as ResearchCycle[] | undefined) ?? []
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
        <span v-for="skill in run.skills" :key="skill.id || skill.name">Skill · {{ skill.name }}</span>
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
      <section v-if="researchTopic(run)" class="research-topic-card">
        <span class="section-kicker">研究主题</span>
        <h3>{{ researchTopic(run)?.title }}</h3>
        <p>{{ researchTopic(run)?.objective }}</p>
        <dl>
          <template v-if="researchTopic(run)?.scope?.length">
            <dt>研究范围</dt>
            <dd>{{ researchTopic(run)?.scope?.join('；') }}</dd>
          </template>
          <template v-if="researchTopic(run)?.key_questions?.length">
            <dt>关键问题</dt>
            <dd>{{ researchTopic(run)?.key_questions?.join('；') }}</dd>
          </template>
          <template v-if="researchTopic(run)?.constraints?.length">
            <dt>约束</dt>
            <dd>{{ researchTopic(run)?.constraints?.join('；') }}</dd>
          </template>
          <dt>交付物</dt>
          <dd>{{ researchTopic(run)?.deliverable }}</dd>
        </dl>
      </section>

      <section v-if="researchCycles(run).length" class="research-cycle-list">
        <span class="section-kicker">计划 · 执行 · 评估</span>
        <article v-for="cycle in researchCycles(run)" :key="cycle.iteration" class="research-cycle-item">
          <header>
            <b>第 {{ cycle.iteration }} 轮</b>
            <span v-if="cycle.evaluation">{{ cycle.evaluation.sufficient ? '证据充分' : '发现证据缺口' }}</span>
          </header>
          <div v-if="cycle.plan"><small>计划</small><p>{{ cycle.plan.focus?.join('；') }}</p></div>
          <div v-if="cycle.execution"><small>执行</small><p>{{ cycle.execution.summary }}</p></div>
          <div v-if="cycle.evaluation"><small>评估</small><p>{{ cycle.evaluation.rationale }}</p></div>
        </article>
      </section>

      <div v-if="run.status === 'awaiting_confirmation'" class="run-confirmation">
        <p v-if="run.agent_type === 'research'">确认后才会启动 Deep Agents 的计划、执行、评估循环，并在循环结束后生成报告。</p>
        <p v-else>确认后才会生成新的 PPTX；原版本不会被覆盖。</p>
        <button type="button" class="primary-action" @click="$emit('command', run, 'confirm')">确认并继续</button>
        <button type="button" @click="$emit('command', run, 'cancel')">取消</button>
      </div>

      <section v-if="run.artifacts.length" class="artifact-grid">
        <article v-for="artifact in run.artifacts" :key="artifact.id" class="artifact-card">
          <img v-if="artifact.type === 'image' && previews[artifact.id]" :src="previews[artifact.id]" :alt="artifact.name" />
          <div v-else-if="artifact.type === 'image'" class="artifact-file-icon">IMG</div>
          <div v-else class="artifact-file-icon">{{ artifact.type === 'pptx' ? 'P' : 'MD' }}</div>
          <div class="artifact-copy">
            <span>{{ artifact.type.toUpperCase() }} · v{{ artifact.version }}</span>
            <b>{{ artifact.name }}</b>
            <small>{{ Math.ceil(artifact.size / 1024) }} KB</small>
            <ol v-if="artifact.type === 'pptx' && artifactTitles(artifact.metadata).length" class="slide-preview-list">
              <li v-for="title in artifactTitles(artifact.metadata).slice(0, 5)" :key="title">{{ title }}</li>
            </ol>
            <button class="artifact-download" type="button" @click="downloadArtifact(artifact.download_url, artifact.name)">下载产物 ↓</button>
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
