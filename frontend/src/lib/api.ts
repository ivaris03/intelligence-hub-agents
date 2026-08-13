export type AgentType = 'image' | 'slides' | 'research'
export type ThinkingEffort = 'none' | 'low' | 'medium' | 'high'
export type StreamEvent = { type: string; seq: number; [key: string]: unknown }

export type CurrentUser = {
  id: string
  phone: string
  display_name: string
  role: 'admin' | 'member'
  permissions: string[]
  is_active: boolean
  created_at: string
}

export type AuthToken = {
  access_token: string
  token_type: 'bearer'
  expires_in: number
  user: CurrentUser
}

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

export type MemoryChatMessage = {
  id: string
  role: 'user' | 'assistant'
  content: string
  memory_changed: boolean
  created_at: string
}

export type MemoryChatResponse = {
  user_message: MemoryChatMessage
  assistant_message: MemoryChatMessage
  summary: MemorySummary
  changed: boolean
}

export type MemoryRefineResponse = {
  added_facts: number
  processed_messages: number
  summary: MemorySummary
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
  chat_model: string
  agent_model: string
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
  thinking_effort?: ThinkingEffort
}

function apiErrorMessage(detail: unknown): string | null {
  if (typeof detail === 'string') return detail
  if (!Array.isArray(detail)) return null
  const messages = detail
    .map((item) => {
      if (typeof item === 'string') return item
      if (item && typeof item === 'object' && 'msg' in item) return String(item.msg)
      return ''
    })
    .filter(Boolean)
  return messages.length ? messages.join('；') : null
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, withAuth(init))
  if (!response.ok) {
    let detail = `请求失败（${response.status}）`
    try {
      const body = (await response.json()) as { detail?: unknown }
      detail = apiErrorMessage(body.detail) ?? detail
    } catch {
      // Keep the safe status-only fallback.
    }
    throw new Error(detail)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

function withAuth(init: RequestInit = {}): RequestInit {
  const token = localStorage.getItem('ih_access_token')
  return {
    ...init,
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init.headers ?? {}),
    },
  }
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
  const response = await fetch(path, withAuth({ ...init, signal, headers: { Accept: 'text/event-stream', ...(init.headers ?? {}) } }))
  if (!response.ok || !response.body) {
    let message = `请求失败（${response.status}）`
    try {
      const payload = (await response.json()) as { detail?: unknown }
      message = apiErrorMessage(payload.detail) ?? message
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
  regenerate: (
    id: string,
    thinkingEffort: ThinkingEffort,
    onEvent: (event: StreamEvent) => void,
    signal?: AbortSignal,
  ) =>
    streamResponse(
      `/api/messages/${id}/regenerate`,
      jsonInit('POST', { thinking_effort: thinkingEffort }),
      onEvent,
      signal,
    ),
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
    const token = localStorage.getItem('ih_access_token')
    if (token) request.setRequestHeader('Authorization', `Bearer ${token}`)
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
  messages: () => api<MemoryChatMessage[]>('/api/memory-summary/messages'),
  chat: (content: string) =>
    api<MemoryChatResponse>('/api/memory-summary/messages', jsonInit('POST', { content })),
  clearMessages: () => api<void>('/api/memory-summary/messages', { method: 'DELETE' }),
  refine: () => api<MemoryRefineResponse>('/api/memory-summary/refine', { method: 'POST' }),
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
      thinking_effort?: ThinkingEffort
    },
    onEvent: (event: StreamEvent) => void,
    signal?: AbortSignal,
  ) => streamResponse('/api/agent-runs', jsonInit('POST', payload), onEvent, signal),
  command: (
    id: string,
    action: 'confirm' | 'cancel' | 'retry' | 'revise',
    onEvent?: (event: StreamEvent) => void,
    signal?: AbortSignal,
    input?: string,
  ) => {
    if (action === 'cancel') return api<AgentRun>(`/api/agent-runs/${id}/commands`, jsonInit('POST', { action }))
    return streamResponse(
      `/api/agent-runs/${id}/commands`,
      jsonInit('POST', { action, ...(input ? { input } : {}) }),
      onEvent ?? (() => undefined),
      signal,
    )
  },
  resume: (id: string, onEvent: (event: StreamEvent) => void, signal?: AbortSignal) =>
    streamResponse(`/api/agent-runs/${id}/resume`, { method: 'POST' }, onEvent, signal),
}

export const authApi = {
  login: (phone: string, password: string) =>
    api<AuthToken>('/api/auth/login', jsonInit('POST', { phone, password })),
  me: () => api<CurrentUser>('/api/auth/me'),
  logout: () => api<void>('/api/auth/logout', { method: 'POST' }),
}

export const adminUsersApi = {
  list: (query = '') => api<CurrentUser[]>(`/api/admin/users${query ? `?q=${encodeURIComponent(query)}` : ''}`),
  create: (payload: { phone: string; password: string; display_name: string; role: 'admin' | 'member' }) => api<CurrentUser>('/api/admin/users', jsonInit('POST', payload)),
  update: (id: string, payload: Partial<{ role: 'admin' | 'member'; is_active: boolean }>) => api<CurrentUser>(`/api/admin/users/${id}`, jsonInit('PATCH', payload)),
}

export async function downloadArtifact(url: string, name: string): Promise<void> {
  const response = await fetch(url, withAuth())
  if (!response.ok) throw new Error(`下载失败（${response.status}）`)
  const objectUrl = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = objectUrl
  anchor.download = name
  anchor.click()
  URL.revokeObjectURL(objectUrl)
}

export async function artifactObjectUrl(url: string): Promise<string> {
  const response = await fetch(url, withAuth())
  if (!response.ok) throw new Error(`预览加载失败（${response.status}）`)
  return URL.createObjectURL(await response.blob())
}
