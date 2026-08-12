<script setup lang="ts">
import AppSidebar from '@/components/AppSidebar.vue'
import ChatComposer from '@/components/ChatComposer.vue'
import MessageBubble from '@/components/MessageBubble.vue'
import { useChatStore } from '@/features/chat/chatStore'

const chat = useChatStore()
</script>

<template>
  <div class="app-layout">
    <AppSidebar @new-chat="chat.clear" />
    <main class="chat-main">
      <header class="topbar">
        <div class="mode-switch" aria-label="对话模式">
          <button :class="{ active: chat.mode === 'chat' }" @click="chat.mode = 'chat'">Chat</button>
          <button :class="{ active: chat.mode === 'work' }" @click="chat.mode = 'work'">Work</button>
        </div>
        <select v-if="chat.mode === 'work'" v-model="chat.agentType" class="agent-select">
          <option value="image">图片 Agent</option>
          <option value="slides">演示 Agent</option>
          <option value="research">研究 Agent</option>
        </select>
        <span class="model-pill">Qwen · 自动</span>
      </header>

      <section class="conversation-view">
        <div v-if="chat.messages.length === 0" class="empty-state">
          <div class="hero-mark">✦</div>
          <p class="eyebrow">YOUR PERSONAL AGENT SPACE</p>
          <h1>今天想探索什么？</h1>
          <p>对话、研究，或把一个想法变成可交付的作品。</p>
          <div class="suggestions">
            <button @click="chat.send('帮我梳理一个新项目的思路')"><b>梳理思路</b><span>把模糊想法变清晰</span></button>
            <button @click="chat.send('介绍一下你现在能做什么')"><b>认识 Hub</b><span>看看当前能力边界</span></button>
            <button @click="chat.mode = 'work'"><b>启动 Agent</b><span>制作图片、演示或研究报告</span></button>
          </div>
        </div>
        <div v-else class="message-list">
          <MessageBubble v-for="message in chat.messages" :key="message.id" :message="message" />
        </div>
      </section>

      <ChatComposer :streaming="chat.isStreaming" @send="chat.send" @stop="chat.stop" />
    </main>
  </div>
</template>

