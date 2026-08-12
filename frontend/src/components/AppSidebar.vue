<script setup lang="ts">
defineEmits<{ newChat: [] }>()
</script>

<template>
  <aside class="sidebar">
    <div class="brand">
      <span class="brand-mark">IH</span>
      <span>Intelligence Hub</span>
    </div>
    <button class="new-chat" type="button" @click="$emit('newChat')">
      <span>＋</span> 新会话
    </button>
    <p class="sidebar-label">最近</p>
    <nav class="conversation-list" aria-label="会话列表">
      <a class="conversation active" href="#">
        <span class="conversation-dot"></span>
        <span>开始探索 Intelligence Hub</span>
      </a>
    </nav>
    <div class="sidebar-footer">
      <RouterLink to="/settings" class="sidebar-link">⚙ 设置</RouterLink>
      <div class="profile"><span>S</span><div><b>Personal</b><small>本地工作区</small></div></div>
    </div>
  </aside>
</template>

