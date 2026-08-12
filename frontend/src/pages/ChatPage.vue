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
</script>

<template>
  <div class="app-layout">
    <AppSidebar />
    <main class="chat-main">
      <header class="topbar">
        <div class="mode-switch" aria-label="对话模式">
          <button :class="{ active: chat.mode === 'chat' }" :disabled="chat.isStreaming" @click="chat.mode = 'chat'">Chat</button>
          <button :class="{ active: chat.mode === 'work' }" :disabled="chat.isStreaming" @click="chat.mode = 'work'">Work</button>
        </div>
        <template v-if="chat.mode === 'work'">
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
        <span class="conversation-title">{{ chat.activeConversation?.title }}</span>
        <span class="model-pill">Qwen · 服务端</span>
      </header>

      <section ref="conversationView" class="conversation-view" aria-live="polite">
        <div v-if="chat.error" class="global-error">
          <span>{{ chat.error }}</span><button type="button" @click="chat.error = ''">×</button>
        </div>
        <div v-if="chat.loading && !chat.timeline.length" class="loading-state"><span></span>正在恢复会话…</div>
        <div v-else-if="chat.timeline.length === 0" class="empty-state">
          <div class="hero-mark">✦</div>
          <p class="eyebrow">YOUR PERSONAL AGENT SPACE</p>
          <h1>今天想探索什么？</h1>
          <p>对话、研究，或把一个想法变成可交付的作品。</p>
          <div class="suggestions">
            <button @click="send('帮我梳理一个新项目的思路')"><b>梳理思路</b><span>把模糊想法变清晰</span></button>
            <button @click="send('介绍一下你现在能做什么')"><b>认识 Hub</b><span>看看当前能力边界</span></button>
            <button @click="chat.mode = 'work'"><b>启动 Agent</b><span>制作图片、演示或研究报告</span></button>
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
