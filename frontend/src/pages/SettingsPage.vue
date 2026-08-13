<template>
  <div class="settings-layout">
    <aside class="settings-nav">
      <RouterLink to="/" class="back-link">← 返回对话</RouterLink>
      <h2>设置</h2>
      <RouterLink :to="{ name: 'settings-general' }">通用</RouterLink>
      <RouterLink :to="{ name: 'settings-mcp' }">MCP</RouterLink>
      <RouterLink :to="{ name: 'settings-skill' }">Skill</RouterLink>
      <RouterLink :to="{ name: 'settings-memory' }">Memory</RouterLink>
    </aside>
    <main class="settings-content">
      <p class="eyebrow">SETTINGS</p>
      <h1>让 Hub 更适合你</h1>
      <RouterView />
    </main>
  </div>
</template>
