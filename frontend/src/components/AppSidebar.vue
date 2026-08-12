<script setup lang="ts">
import { ref, watch } from 'vue'

import { useChatStore } from '@/features/chat/chatStore'

const chat = useChatStore()
const search = ref('')
const editingId = ref<string | null>(null)
const renameDraft = ref('')
const pendingDeleteId = ref<string | null>(null)
let timer: ReturnType<typeof setTimeout> | undefined

watch(search, (value) => {
  clearTimeout(timer)
  timer = setTimeout(() => chat.refreshConversations(value.trim()), 220)
})

function startRename(id: string, current: string) {
  editingId.value = id
  renameDraft.value = current
  pendingDeleteId.value = null
}

function commitRename(id: string, current: string) {
  if (editingId.value !== id) return
  const title = renameDraft.value.trim()
  editingId.value = null
  if (title && title !== current) void chat.renameConversation(id, title)
}

function confirmRemove(id: string) {
  pendingDeleteId.value = null
  void chat.removeConversation(id)
}
</script>

<template>
  <aside class="sidebar">
    <div class="brand">
      <span class="brand-mark">IH</span>
      <span>Intelligence Hub</span>
    </div>
    <button class="new-chat" type="button" :disabled="chat.isStreaming" @click="chat.createConversation">
      <span>＋</span> 新会话
    </button>
    <label class="sidebar-search">
      <span>⌕</span>
      <input v-model="search" type="search" placeholder="搜索标题或消息" aria-label="搜索会话" />
    </label>
    <p class="sidebar-label">{{ search ? '搜索结果' : '最近' }}</p>
    <nav class="conversation-list" aria-label="会话列表">
      <div
        v-for="conversation in chat.conversations"
        :key="conversation.id"
        class="conversation-row"
        :class="{ active: conversation.id === chat.activeConversationId }"
      >
        <input
          v-if="editingId === conversation.id"
          v-model="renameDraft"
          class="conversation-title-editor"
          aria-label="会话标题"
          maxlength="120"
          autofocus
          @click.stop
          @keydown.enter.prevent="commitRename(conversation.id, conversation.title)"
          @keydown.escape.prevent="editingId = null"
          @blur="commitRename(conversation.id, conversation.title)"
        />
        <button v-else class="conversation" type="button" @click="chat.selectConversation(conversation.id)">
          <span class="conversation-dot"></span>
          <span class="conversation-copy">
            <b>{{ conversation.title }}</b>
            <small v-if="conversation.match_snippet">{{ conversation.match_snippet }}</small>
          </span>
        </button>
        <div class="conversation-actions">
          <template v-if="pendingDeleteId === conversation.id">
            <button type="button" title="确认删除" aria-label="确认删除会话" @click.stop="confirmRemove(conversation.id)">✓</button>
            <button type="button" title="取消删除" aria-label="取消删除会话" @click.stop="pendingDeleteId = null">↩</button>
          </template>
          <template v-else>
            <button type="button" title="重命名" @click.stop="startRename(conversation.id, conversation.title)">✎</button>
            <button type="button" title="删除" @click.stop="pendingDeleteId = conversation.id">×</button>
          </template>
        </div>
      </div>
      <p v-if="chat.conversations.length === 0" class="sidebar-empty">没有匹配的会话</p>
    </nav>
    <div class="sidebar-footer">
      <RouterLink to="/settings" class="sidebar-link">⚙ 设置</RouterLink>
      <div class="profile"><span>S</span><div><b>Personal</b><small>本地工作区</small></div></div>
    </div>
  </aside>
</template>
