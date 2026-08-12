<template>
  <div class="settings-layout">
    <aside class="settings-nav">
      <RouterLink to="/" class="back-link">← 返回对话</RouterLink>
      <h2>设置</h2>
      <a class="active" href="#appearance">外观</a>
      <a href="#mcp">MCP</a>
      <a href="#skill">Skill</a>
      <a href="#memory">Memory</a>
    </aside>
    <main class="settings-content">
      <p class="eyebrow">SETTINGS</p>
      <h1>让 Hub 更适合你</h1>
      <section id="appearance" class="settings-card">
        <div><h3>外观</h3><p>跟随系统主题，界面语言为简体中文。</p></div>
        <select><option>跟随系统</option><option>浅色</option><option>深色</option></select>
      </section>
      <section id="mcp" class="settings-card">
        <div><h3>MCP</h3><p>管理联网搜索等外部工具服务及其连接状态。</p></div>
        <span class="status-badge">等待检测</span>
      </section>
      <section id="skill" class="settings-card">
        <div><h3>Skill</h3><p>创建可复用的任务说明，并在对话中通过 @ 调用。</p></div>
        <button>管理 Skill</button>
      </section>
      <section id="memory" class="settings-card">
        <div><h3>Memory</h3><p>允许 Hub 使用你主动保存的偏好与背景信息。</p></div>
        <label class="switch"><input type="checkbox" checked /><span></span></label>
      </section>
    </main>
  </div>
</template>
