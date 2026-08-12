export type StreamEvent =
  | { type: 'reasoning.delta' | 'message.delta'; seq: number; delta: string }
  | { type: 'completed'; seq: number }
  | { type: 'failed'; seq: number; message: string }

type ChatPayload = {
  content: string
  mode: 'chat' | 'work'
  agent_type?: 'image' | 'slides' | 'research'
}

function parseFrame(frame: string): StreamEvent | null {
  const event = frame.match(/^event: (.+)$/m)?.[1]
  const data = frame.match(/^data: (.+)$/m)?.[1]
  if (!event || !data) return null
  return { type: event, ...JSON.parse(data) } as StreamEvent
}

export async function streamChat(
  payload: ChatPayload,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch('/api/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(payload),
    signal,
  })
  if (!response.ok || !response.body) {
    throw new Error(`请求失败（${response.status}）`)
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

