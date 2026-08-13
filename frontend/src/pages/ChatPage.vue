<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'

import AgentRunCard from '@/components/AgentRunCard.vue'
import AppSidebar from '@/components/AppSidebar.vue'
import ChatComposer from '@/components/ChatComposer.vue'
import MessageBubble from '@/components/MessageBubble.vue'
import { useChatStore } from '@/features/chat/chatStore'

const chat = useChatStore()
const draft = ref('')
const conversationView = ref<HTMLElement | null>(null)

onMounted(() => chat.initialize())
watch(
  () => [chat.timeline.length, chat.messages.at(-1)?.content.length, chat.runs.at(-1)?.events.length],
  async () => {
    await nextTick()
    if (conversationView.value) conversationView.value.scrollTop = conversationView.value.scrollHeight
  },
)

function send(value: string) {
  void chat.send(value)
}

function sendWithAgent(agentType: 'image' | 'slides' | 'research', value: string) {
  chat.agentType = agentType
  void chat.send(value)
}
</script>

<template>
  <div class="app-layout">
    <AppSidebar />
    <main class="chat-main">
      <header class="topbar">
        <span v-if="chat.activeConversation || chat.pendingMode" class="session-mode-pill">
          {{ chat.mode === 'chat' ? 'Chat' : 'Work' }}
        </span>
        <template v-if="(chat.activeConversation || chat.pendingMode) && chat.mode === 'work'">
          <select v-model="chat.agentType" class="agent-select" aria-label="选择 Agent" :disabled="chat.isStreaming">
            <option value="image">图片 Agent</option>
            <option value="slides">演示 Agent</option>
            <option value="research">研究 Agent</option>
          </select>
          <select
            v-if="chat.agentType === 'slides' && chat.slideArtifacts.length"
            v-model="chat.sourceArtifactId"
            class="agent-select source-select"
            :disabled="chat.isStreaming"
            aria-label="选择演示源版本"
            title="选择源版本即进入定向修改"
          >
            <option value="">新建演示</option>
            <option v-for="artifact in chat.slideArtifacts" :key="artifact.id" :value="artifact.id">
              修改 {{ artifact.name }} · v{{ artifact.version }}
            </option>
          </select>
        </template>
        <span class="conversation-title">
          {{ chat.activeConversation?.title ?? (chat.pendingMode ? '等待第一句话…' : '新会话') }}
        </span>
        <span class="model-pill">Qwen · 服务端</span>
      </header>

      <section ref="conversationView" class="conversation-view" aria-live="polite">
        <div v-if="chat.error" class="global-error">
          <span>{{ chat.error }}</span><button type="button" @click="chat.error = ''">×</button>
        </div>
        <div v-if="chat.choosingMode" class="empty-state mode-choice">
          <div class="hero-mark">✦</div>
          <p class="eyebrow">CREATE A SESSION</p>
          <h1>这次要做什么？</h1>
          <p>会话创建后类型固定，Chat 和 Work 不会共用上下文。</p>
          <div class="suggestions mode-options">
            <button type="button" @click="chat.chooseMode('chat')">
              <b>Chat</b><span>普通问答、文件问答与联网搜索</span>
            </button>
            <button type="button" @click="chat.chooseMode('work')">
              <b>Work</b><span>使用 Agent 生成图片、演示或研究报告</span>
            </button>
          </div>
        </div>
        <div v-else-if="chat.loading && !chat.timeline.length" class="loading-state"><span></span>正在恢复会话…</div>
        <div v-else-if="chat.timeline.length === 0" class="empty-state">
          <div class="hero-mark">✦</div>
          <p class="eyebrow">YOUR PERSONAL AGENT SPACE</p>
          <h1>{{ chat.mode === 'chat' ? '今天想探索什么？' : '今天想交付什么？' }}</h1>
          <p>{{ chat.mode === 'chat' ? '从一段独立对话开始。' : '图片、演示和研究任务会保存在独立的 Work 会话中。' }}</p>
          <div class="suggestions">
            <template v-if="chat.mode === 'chat'">
              <button @click="send('帮我梳理一个新项目的思路')"><b>梳理思路</b><span>把模糊想法变清晰</span></button>
              <button @click="send('介绍一下你现在能做什么')"><b>认识 Hub</b><span>看看当前能力边界</span></button>
              <button @click="send('总结这段材料并列出行动项')"><b>总结材料</b><span>提炼重点和下一步行动</span></button>
            </template>
            <template v-else>
              <button @click="sendWithAgent('image', '生成一张绿色知识中心插画')"><b>生成图片</b><span>用图片 Agent 创作视觉</span></button>
              <button @click="sendWithAgent('slides', '制作一份项目介绍演示')"><b>制作演示</b><span>生成可下载的演示文稿</span></button>
              <button @click="sendWithAgent('research', '研究这个主题并给出带引用的报告')"><b>深度研究</b><span>使用研究 Agent 搜集信息</span></button>
            </template>
          </div>
        </div>
        <div v-else class="message-list">
          <template v-for="item in chat.timeline" :key="item.kind === 'message' ? item.message.id : item.run.id">
            <MessageBubble
              v-if="item.kind === 'message'"
              :message="item.message"
              @follow-up="draft = $event"
              @regenerate="chat.regenerate"
            />
            <AgentRunCard v-else :run="item.run" @command="chat.runCommand" />
          </template>
        </div>
      </section>

      <ChatComposer
        v-if="(chat.activeConversation || chat.pendingMode) && !chat.choosingMode"
        v-model="draft"
        v-model:selected-skill-id="chat.selectedSkillId"
        :streaming="chat.isStreaming"
        :files="chat.files"
        :selected-file-ids="chat.selectedFileIds"
        :skills="chat.enabledSkills"
        :upload-progress="chat.uploadProgress"
        @send="send"
        @stop="chat.stop"
        @add-files="chat.addFiles"
        @toggle-file="chat.toggleFile"
      />
    </main>
  </div>
</template>
