import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import {
  conversationsApi,
  messagesApi,
  runsApi,
  skillsApi,
  uploadFile,
  type AgentRun,
  type AgentType,
  type Artifact,
  type Conversation,
  type FileRecord,
  type Message,
  type RunEvent,
  type Skill,
  type StreamEvent,
  type ToolCall,
} from '@/lib/api'

export type { AgentRun, Message }
export type TimelineItem =
  | { kind: 'message'; createdAt: string; message: Message }
  | { kind: 'run'; createdAt: string; run: AgentRun }

function now() {
  return new Date().toISOString()
}

function emptyMessage(content = ''): Message {
  return {
    id: `pending-${crypto.randomUUID()}`,
    conversation_id: '',
    role: 'assistant',
    mode: 'chat',
    content,
    reasoning: '',
    status: 'streaming',
    created_at: now(),
    parts: [],
    tool_calls: [],
    files: [],
  }
}

function emptyRun(conversationId: string, agentType: AgentType, input: string): AgentRun {
  return {
    id: `pending-${crypto.randomUUID()}`,
    conversation_id: conversationId,
    agent_type: agentType,
    intent: 'CREATE',
    input,
    stage: 'queued',
    status: 'queued',
    answer: '',
    public_state: {},
    events: [],
    artifacts: [],
    files: [],
    created_at: now(),
    updated_at: now(),
  }
}

export const useChatStore = defineStore('chat', () => {
  const conversations = ref<Conversation[]>([])
  const activeConversationId = ref<string | null>(null)
  const messages = ref<Message[]>([])
  const runs = ref<AgentRun[]>([])
  const files = ref<FileRecord[]>([])
  const skills = ref<Skill[]>([])
  const mode = ref<'chat' | 'work'>('chat')
  const agentType = ref<AgentType>('image')
  const selectedFileIds = ref<string[]>([])
  const selectedSkillId = ref('')
  const sourceArtifactId = ref('')
  const controller = ref<AbortController | null>(null)
  const activeMessageId = ref<string | null>(null)
  const activeRunId = ref<string | null>(null)
  const loading = ref(false)
  const error = ref('')
  const uploadProgress = ref<Record<string, number>>({})

  const activeConversation = computed(
    () => conversations.value.find((item) => item.id === activeConversationId.value) ?? null,
  )
  const enabledSkills = computed(() => skills.value.filter((skill) => skill.enabled))
  const isStreaming = computed(() => controller.value !== null)
  const slideArtifacts = computed(() =>
    runs.value.flatMap((run) => run.artifacts).filter((artifact) => artifact.type === 'pptx'),
  )
  const timeline = computed<TimelineItem[]>(() => {
    const items: TimelineItem[] = [
      ...messages.value.map((message) => ({ kind: 'message' as const, createdAt: message.created_at, message })),
      ...runs.value.map((run) => ({ kind: 'run' as const, createdAt: run.created_at, run })),
    ]
    return items.sort((left, right) => left.createdAt.localeCompare(right.createdAt))
  })

  function report(cause: unknown) {
    error.value = cause instanceof Error ? cause.message : '操作失败，请重试'
  }

  async function initialize() {
    loading.value = true
    error.value = ''
    try {
      const [items, skillItems] = await Promise.all([conversationsApi.list(), skillsApi.list()])
      conversations.value = items
      skills.value = skillItems
      if (!items.length) {
        const created = await conversationsApi.create()
        conversations.value = [created]
      }
      await selectConversation(activeConversationId.value ?? conversations.value[0].id)
    } catch (cause) {
      report(cause)
    } finally {
      loading.value = false
    }
  }

  async function refreshConversations(query = '') {
    try {
      conversations.value = await conversationsApi.list(query)
    } catch (cause) {
      report(cause)
    }
  }

  async function selectConversation(id: string) {
    if (isStreaming.value) stop()
    activeConversationId.value = id
    selectedFileIds.value = []
    sourceArtifactId.value = ''
    loading.value = true
    try {
      const [messageItems, fileItems, runItems] = await Promise.all([
        conversationsApi.messages(id),
        conversationsApi.files(id),
        conversationsApi.runs(id),
      ])
      messages.value = messageItems
      files.value = fileItems
      runs.value = runItems
    } catch (cause) {
      report(cause)
    } finally {
      loading.value = false
    }
  }

  async function createConversation() {
    if (isStreaming.value) return
    try {
      const created = await conversationsApi.create()
      conversations.value.unshift(created)
      await selectConversation(created.id)
    } catch (cause) {
      report(cause)
    }
  }

  async function renameConversation(id: string, title: string) {
    if (!title.trim()) return
    try {
      const updated = await conversationsApi.rename(id, title.trim())
      const index = conversations.value.findIndex((item) => item.id === id)
      if (index >= 0) conversations.value[index] = updated
    } catch (cause) {
      report(cause)
    }
  }

  async function removeConversation(id: string) {
    try {
      await conversationsApi.remove(id)
      conversations.value = conversations.value.filter((item) => item.id !== id)
      if (!conversations.value.length) {
        await createConversation()
      } else if (activeConversationId.value === id) {
        await selectConversation(conversations.value[0].id)
      }
    } catch (cause) {
      report(cause)
    }
  }

  function handleMessageEvent(answer: Message, event: StreamEvent) {
    if (event.type === 'message.created') {
      answer.id = String(event.message_id)
      activeMessageId.value = answer.id
    }
    if (event.type === 'message.delta') answer.content += String(event.delta ?? '')
    if (event.type === 'message.finalized') answer.content = String(event.content ?? answer.content)
    if (event.type === 'reasoning.delta') answer.reasoning += String(event.delta ?? '')
    if (event.type === 'skill.selected') {
      answer.skill = {
        id: String(event.id ?? ''),
        name: String(event.name ?? ''),
        description: String(event.description ?? ''),
      }
    }
    if (event.type === 'tool.started') {
      answer.tool_calls.push({
        id: String(event.id),
        seq: answer.tool_calls.length + 1,
        tool_name: String(event.name),
        input_summary: String(event.input_summary ?? ''),
        output_summary: '',
        status: String(event.status ?? 'running'),
        duration_ms: null,
      })
    }
    if (event.type === 'tool.completed' || event.type === 'tool.failed') {
      const call = answer.tool_calls.find((item) => item.id === String(event.id))
      if (call) {
        call.status = String(event.status)
        call.output_summary = String(event.output_summary ?? '')
        call.duration_ms = Number(event.duration_ms ?? 0)
      }
    }
    if (event.type === 'sources.finalized') {
      answer.parts.push({ seq: 3, type: 'sources', content: '', data: { items: event.items } })
    }
    if (event.type === 'follow_up.finalized') answer.follow_up = String(event.text)
    if (event.type === 'title.updated') {
      const conversation = conversations.value.find((item) => item.id === String(event.conversation_id))
      if (conversation) conversation.title = String(event.title)
    }
    if (event.type === 'completed') answer.status = 'completed'
    if (event.type === 'cancelled') answer.status = 'cancelled'
    if (event.type === 'failed') {
      answer.status = 'failed'
      answer.error = String(event.message ?? '生成失败')
      if (!answer.content) answer.content = answer.error
    }
  }

  function handleRunEvent(run: AgentRun, event: StreamEvent) {
    if (event.run_id) {
      run.id = String(event.run_id)
      activeRunId.value = run.id
    }
    const storedEvent: RunEvent = {
      seq: Number(event.seq),
      type: event.type,
      payload: Object.fromEntries(Object.entries(event).filter(([key]) => !['type', 'seq', 'run_id'].includes(key))),
      created_at: now(),
    }
    run.events.push(storedEvent)
    if (event.type === 'run.created') {
      run.intent = String(event.intent) as AgentRun['intent']
      run.status = String(event.status) as AgentRun['status']
      if (event.public_state) run.public_state = event.public_state as Record<string, unknown>
      if (event.skill) run.skill = event.skill as AgentRun['skill']
    }
    if (event.type === 'run.stage') {
      run.stage = String(event.stage)
      run.status = String(event.status) as AgentRun['status']
    }
    if (event.type === 'brief.ready') run.public_state.image_brief = event.brief
    if (event.type === 'outline.ready') {
      if (event.outline) run.public_state.outline = event.outline
      if (event.modification_plan) run.public_state.modification_plan = event.modification_plan
    }
    if (event.type === 'artifact.created') {
      const artifact = event.artifact as Artifact
      if (!run.artifacts.some((item) => item.id === artifact.id)) run.artifacts.push(artifact)
    }
    if (event.type === 'message.delta') run.answer += String(event.delta ?? '')
    if (event.type === 'completed') run.status = String(event.status ?? 'completed') as AgentRun['status']
    if (event.type === 'cancelled') run.status = 'cancelled'
    if (event.type === 'failed') {
      run.status = 'failed'
      run.error = String(event.message ?? 'Agent 执行失败')
    }
    run.updated_at = now()
  }

  async function send(content: string) {
    const conversationId = activeConversationId.value
    if (!conversationId || !content.trim() || isStreaming.value) return
    error.value = ''
    if (mode.value === 'work') {
      await sendWork(content.trim(), conversationId)
      return
    }
    const user: Message = {
      ...emptyMessage(content.trim()),
      id: `local-${crypto.randomUUID()}`,
      conversation_id: conversationId,
      role: 'user',
      content: content.trim(),
      status: 'completed',
      files: files.value.filter((file) => selectedFileIds.value.includes(file.id)),
    }
    const answer = { ...emptyMessage(), conversation_id: conversationId }
    messages.value.push(user, answer)
    controller.value = new AbortController()
    try {
      await conversationsApi.streamMessage(
        conversationId,
        {
          content: content.trim(),
          mode: 'chat',
          file_ids: selectedFileIds.value,
          ...(selectedSkillId.value ? { skill_id: selectedSkillId.value } : {}),
        },
        (event) => handleMessageEvent(answer, event),
        controller.value.signal,
      )
      selectedFileIds.value = []
      await reloadActive()
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === 'AbortError') answer.status = 'cancelled'
      else {
        answer.status = 'failed'
        answer.error = cause instanceof Error ? cause.message : '请求失败'
        report(cause)
      }
    } finally {
      controller.value = null
      activeMessageId.value = null
    }
  }

  async function sendWork(content: string, conversationId: string) {
    const selectedFiles = files.value.filter((file) => selectedFileIds.value.includes(file.id))
    if (agentType.value === 'image' && selectedFiles.some((file) => file.kind !== 'image')) {
      error.value = '图片 Agent 只能使用图片作为参考文件'
      return
    }
    const run = emptyRun(conversationId, agentType.value, content)
    run.files = selectedFiles
    run.skill = skills.value.find((skill) => skill.id === selectedSkillId.value) ?? null
    runs.value.push(run)
    controller.value = new AbortController()
    try {
      await runsApi.start(
        {
          conversation_id: conversationId,
          agent_type: agentType.value,
          input: content,
          file_ids: selectedFileIds.value,
          ...(selectedSkillId.value ? { skill_id: selectedSkillId.value } : {}),
          ...(agentType.value === 'slides' && sourceArtifactId.value
            ? { intent: 'MODIFY' as const, source_artifact_id: sourceArtifactId.value }
            : {}),
        },
        (event) => handleRunEvent(run, event),
        controller.value.signal,
      )
      selectedFileIds.value = []
      sourceArtifactId.value = ''
      await reloadActive()
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === 'AbortError') run.status = 'cancelled'
      else {
        run.status = 'failed'
        run.error = cause instanceof Error ? cause.message : '运行失败'
        report(cause)
      }
    } finally {
      controller.value = null
      activeRunId.value = null
    }
  }

  async function reloadActive() {
    if (!activeConversationId.value) return
    const id = activeConversationId.value
    const [messageItems, fileItems, runItems, conversationItems] = await Promise.all([
      conversationsApi.messages(id),
      conversationsApi.files(id),
      conversationsApi.runs(id),
      conversationsApi.list(),
    ])
    messages.value = messageItems
    files.value = fileItems
    runs.value = runItems
    conversations.value = conversationItems
  }

  async function regenerate(message: Message) {
    if (isStreaming.value || message.role !== 'assistant') return
    const answer = { ...emptyMessage(), conversation_id: message.conversation_id }
    messages.value.push(answer)
    controller.value = new AbortController()
    try {
      await messagesApi.regenerate(message.id, (event) => handleMessageEvent(answer, event), controller.value.signal)
      await reloadActive()
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === 'AbortError') answer.status = 'cancelled'
      else {
        answer.status = 'failed'
        report(cause)
      }
    } finally {
      controller.value = null
      activeMessageId.value = null
    }
  }

  async function runCommand(run: AgentRun, action: 'confirm' | 'cancel' | 'retry' | 'resume') {
    if (isStreaming.value) return
    error.value = ''
    if (action === 'cancel') {
      try {
        await runsApi.command(run.id, 'cancel')
        await reloadActive()
      } catch (cause) {
        report(cause)
      }
      return
    }
    controller.value = new AbortController()
    activeRunId.value = run.id
    run.events = []
    try {
      if (action === 'resume') await runsApi.resume(run.id, (event) => handleRunEvent(run, event), controller.value.signal)
      else await runsApi.command(run.id, action, (event) => handleRunEvent(run, event), controller.value.signal)
      await reloadActive()
    } catch (cause) {
      run.status = 'failed'
      report(cause)
    } finally {
      controller.value = null
      activeRunId.value = null
    }
  }

  async function stop() {
    if (activeMessageId.value && !activeMessageId.value.startsWith('pending-')) {
      void messagesApi.stop(activeMessageId.value).catch(() => undefined)
    }
    if (activeRunId.value && !activeRunId.value.startsWith('pending-')) {
      void runsApi.command(activeRunId.value, 'cancel').catch(() => undefined)
    }
    controller.value?.abort()
  }

  async function addFiles(fileList: FileList | File[]) {
    const conversationId = activeConversationId.value
    if (!conversationId) return
    const pending = Array.from(fileList)
    if (pending.length + selectedFileIds.value.length > 3) {
      error.value = '单条消息最多选择 3 个文件'
      return
    }
    for (const file of pending) {
      uploadProgress.value[file.name] = 0
      try {
        const stored = await uploadFile(conversationId, file, (progress) => {
          uploadProgress.value[file.name] = progress
        })
        files.value.unshift(stored)
        selectedFileIds.value.push(stored.id)
      } catch (cause) {
        report(cause)
      } finally {
        delete uploadProgress.value[file.name]
      }
    }
  }

  function toggleFile(id: string) {
    if (selectedFileIds.value.includes(id)) {
      selectedFileIds.value = selectedFileIds.value.filter((item) => item !== id)
    } else if (selectedFileIds.value.length < 3) {
      selectedFileIds.value.push(id)
    } else {
      error.value = '单条消息最多选择 3 个文件'
    }
  }

  return {
    conversations,
    activeConversationId,
    activeConversation,
    messages,
    runs,
    files,
    skills,
    enabledSkills,
    mode,
    agentType,
    selectedFileIds,
    selectedSkillId,
    sourceArtifactId,
    slideArtifacts,
    timeline,
    isStreaming,
    loading,
    error,
    uploadProgress,
    initialize,
    refreshConversations,
    selectConversation,
    createConversation,
    renameConversation,
    removeConversation,
    send,
    stop,
    regenerate,
    runCommand,
    addFiles,
    toggleFile,
    reloadActive,
  }
})
