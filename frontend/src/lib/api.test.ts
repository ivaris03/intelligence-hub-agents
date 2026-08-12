import { describe, expect, it, vi } from 'vitest'

import { streamChat } from './api'

describe('streamChat', () => {
  it('parses SSE frames split across chunks', async () => {
    const encoder = new TextEncoder()
    const body = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode('event: message.delta\ndata: {"seq":1,'))
        controller.enqueue(encoder.encode('"delta":"你"}\n\nevent: completed\ndata: {"seq":2}\n\n'))
        controller.close()
      },
    })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(body, { status: 200 })))
    const events: string[] = []
    await streamChat({ content: 'hi', mode: 'chat' }, (event) => events.push(event.type))
    expect(events).toEqual(['message.delta', 'completed'])
    vi.unstubAllGlobals()
  })
})

