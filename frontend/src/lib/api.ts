export type AgentType = 'image' | 'slides' | 'research'
export type StreamEvent = { type: string; seq: number; [key: string]: unknown }

export type Conversation = {
  id: string
  mode: 'chat' | 'work'
  title: string
  title_source: string
  created_at: string
  updated_at: string
  last_activity_at: string
  match_snippet?: string | null
}

export type FileRecord = {
  id: string
  conversation_id: string
  name: string
  mime_type: string
  kind: 'document' | 'image'
  size: number
  status: 'processing' | 'ready' | 'failed'
  error?: string | null
  created_at: string
}

export type SkillSummary = { id?: string | null; name: string; description: string }
export type Skill = SkillSummary & {
  id: string
  instructions: string
  enabled: boolean
  created_at: string
  updated_at: string
}

export type MemorySummary = {
  id: number
  content: string
  source: 'manual' | 'explicit' | 'automatic'
  source_conversation_id?: string | null
  created_at: string
  updated_at: string
}

export type ToolCall = {
  id: string
  seq: number
  tool_name: string
  input_summary: string
  output_summary: string
  status: string
  duration_ms?: number | null
}

export type MessagePart = {
  seq: number
  type: string
  content: string
  data: Record<string, unknown>
}

export type Message = {
  id: string
  conversation_id: string
  role: 'user' | 'assistant'
  mode: 'chat' | 'work'
  agent_type?: AgentType | null
  content: string
  reasoning: string
  follow_up?: string | null
  status: 'streaming' | 'completed' | 'failed' | 'cancelled'
  error?: string | null
  created_at: string
  parts: MessagePart[]
  tool_calls: ToolCall[]
  files: FileRecord[]
  skill?: SkillSummary | null
  skills: SkillSummary[]
  run_id?: string | null
}

export type Artifact = {
  id: string
  run_id: string
  parent_artifact_id?: string | null
  version: number
  type: 'image' | 'pptx' | 'markdown'
  name: string
  mime_type: string
  size: number
  metadata: Record<string, unknown>
  download_url: string
  created_at: string
}

export type RunEvent = {
  seq: number
  type: string
  payload: Record<string, unknown>
  created_at: string
}

export type AgentRun = {
  id: string
  conversation_id: string
  agent_type: AgentType
  intent: 'CREATE' | 'MODIFY' | 'RESUME'
  source_run_id?: string | null
  source_artifact_id?: string | null
  input: string
  stage: string
  status: 'queued' | 'running' | 'awaiting_confirmation' | 'completed' | 'failed' | 'cancelled'
  answer: string
  public_state: Record<string, unknown>
  error?: string | null
  events: RunEvent[]
  artifacts: Artifact[]
  files: FileRecord[]
  skill?: SkillSummary | null
  skills: SkillSummary[]
  created_at: string
  updated_at: string
}

export type AppSettings = {
  memory_enabled: boolean
  web_search_enabled: boolean
  appearance: 'system' | 'light' | 'dark'
  model_ready: boolean
  tavily_ready: boolean
  storage_backend: string
}

type ChatPayload = {
  content: string
  mode: 'chat' | 'work'
  agent_type?: AgentType
  file_ids?: string[]
  skill_id?: string
  skill_ids?: string[]
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  if (!response.ok) {
    let detail = `请求失败（${response.status}）`
    try {
      const body = (await response.json()) as { detail?: string | Array<{ msg: string }> }
      if (typeof body.detail === 'string') detail = body.detail
      else if (Array.isArray(body.detail)) detail = body.detail.map((item) => item.msg).join('；')
    } catch {
      // Keep the safe status-only fallback.
    }
    throw new Error(detail)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

function jsonInit(method: string, payload?: unknown): RequestInit {
  return {
    method,
    headers: { 'Content-Type': 'application/json' },
    ...(payload === undefined ? {} : { body: JSON.stringify(payload) }),
  }
}

function parseFrame(frame: string): StreamEvent | null {
  let event = ''
  const data: string[] = []
  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    if (line.startsWith('data:')) data.push(line.slice(5).trimStart())
  }
  if (!event || data.length === 0) return null
  return { type: event, ...JSON.parse(data.join('\n')) } as StreamEvent
}

async function streamResponse(
  path: string,
  init: RequestInit,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(path, { ...init, signal, headers: { Accept: 'text/event-stream', ...(init.headers ?? {}) } })
  if (!response.ok || !response.body) {
    let message = `请求失败（${response.status}）`
    try {
      const payload = (await response.json()) as { detail?: string }
      if (payload.detail) message = payload.detail
    } catch {
      // Keep status fallback.
    }
    throw new Error(message)
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, '\n')
    const frames = buffer.split('\n\n')
    buffer = frames.pop() ?? ''
    for (const frame of frames) {
      const event = parseFrame(frame)
      if (event) onEvent(event)
    }
    if (done) break
  }
  if (buffer.trim()) {
    const event = parseFrame(buffer)
    if (event) onEvent(event)
  }
}

export function streamChat(
  payload: ChatPayload,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  return streamResponse('/api/chat/stream', jsonInit('POST', payload), onEvent, signal)
}

export const conversationsApi = {
  list: (query = '', mode?: 'chat' | 'work') => {
    const params = new URLSearchParams()
    if (query) params.set('q', query)
    if (mode) params.set('mode', mode)
    const suffix = params.size ? `?${params.toString()}` : ''
    return api<Conversation[]>(`/api/conversations${suffix}`)
  },
  create: (mode: 'chat' | 'work', title?: string) =>
    api<Conversation>('/api/conversations', jsonInit('POST', { mode, ...(title ? { title } : {}) })),
  rename: (id: string, title: string) => api<Conversation>(`/api/conversations/${id}`, jsonInit('PATCH', { title })),
  remove: (id: string) => api<void>(`/api/conversations/${id}`, { method: 'DELETE' }),
  messages: (id: string) => api<Message[]>(`/api/conversations/${id}/messages`),
  files: (id: string) => api<FileRecord[]>(`/api/conversations/${id}/files`),
  runs: (id: string) => api<AgentRun[]>(`/api/conversations/${id}/agent-runs`),
  streamMessage: (
    id: string,
    payload: ChatPayload,
    onEvent: (event: StreamEvent) => void,
    signal?: AbortSignal,
  ) => streamResponse(`/api/conversations/${id}/messages`, jsonInit('POST', payload), onEvent, signal),
}

export const messagesApi = {
  stop: (id: string) => api<Message>(`/api/messages/${id}/stop`, { method: 'POST' }),
  regenerate: (id: string, onEvent: (event: StreamEvent) => void, signal?: AbortSignal) =>
    streamResponse(`/api/messages/${id}/regenerate`, { method: 'POST' }, onEvent, signal),
}

export function uploadFile(
  conversationId: string,
  file: File,
  onProgress: (progress: number) => void,
): Promise<FileRecord> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest()
    const data = new FormData()
    data.append('conversation_id', conversationId)
    data.append('upload', file)
    request.open('POST', '/api/files')
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100))
    }
    request.onload = () => {
      if (request.status >= 200 && request.status < 300) {
        resolve(JSON.parse(request.responseText) as FileRecord)
        return
      }
      try {
        reject(new Error((JSON.parse(request.responseText) as { detail?: string }).detail ?? '上传失败'))
      } catch {
        reject(new Error(`上传失败（${request.status}）`))
      }
    }
    request.onerror = () => reject(new Error('上传失败，请检查网络连接'))
    request.send(data)
  })
}

export const filesApi = {
  remove: (id: string) => api<void>(`/api/files/${id}`, { method: 'DELETE' }),
}

export const skillsApi = {
  list: () => api<Skill[]>('/api/skills'),
  create: (payload: Pick<Skill, 'name' | 'description' | 'instructions' | 'enabled'>) =>
    api<Skill>('/api/skills', jsonInit('POST', payload)),
  update: (id: string, payload: Partial<Pick<Skill, 'name' | 'description' | 'instructions' | 'enabled'>>) =>
    api<Skill>(`/api/skills/${id}`, jsonInit('PATCH', payload)),
  remove: (id: string) => api<void>(`/api/skills/${id}`, { method: 'DELETE' }),
}

export const memorySummaryApi = {
  get: () => api<MemorySummary>('/api/memory-summary'),
  update: (content: string) => api<MemorySummary>('/api/memory-summary', jsonInit('PUT', { content })),
  clear: () => api<void>('/api/memory-summary', { method: 'DELETE' }),
}

export const settingsApi = {
  get: () => api<AppSettings>('/api/settings'),
  update: (payload: Partial<Pick<AppSettings, 'memory_enabled' | 'web_search_enabled' | 'appearance'>>) =>
    api<AppSettings>('/api/settings', jsonInit('PATCH', payload)),
}

export const runsApi = {
  start: (
    payload: {
      conversation_id: string
      agent_type: AgentType
      input: string
      file_ids?: string[]
      skill_ids?: string[]
      intent?: 'CREATE' | 'MODIFY' | 'RESUME'
      source_run_id?: string
      source_artifact_id?: string
    },
    onEvent: (event: StreamEvent) => void,
    signal?: AbortSignal,
  ) => streamResponse('/api/agent-runs', jsonInit('POST', payload), onEvent, signal),
  command: (
    id: string,
    action: 'confirm' | 'cancel' | 'retry',
    onEvent?: (event: StreamEvent) => void,
    signal?: AbortSignal,
  ) => {
    if (action === 'cancel') return api<AgentRun>(`/api/agent-runs/${id}/commands`, jsonInit('POST', { action }))
    return streamResponse(
      `/api/agent-runs/${id}/commands`,
      jsonInit('POST', { action }),
      onEvent ?? (() => undefined),
      signal,
    )
  },
  resume: (id: string, onEvent: (event: StreamEvent) => void, signal?: AbortSignal) =>
    streamResponse(`/api/agent-runs/${id}/resume`, { method: 'POST' }, onEvent, signal),
}
