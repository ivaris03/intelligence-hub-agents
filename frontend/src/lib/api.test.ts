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
    const fetchMock = vi.fn().mockResolvedValue(new Response(body, { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    const events: string[] = []
    await streamChat({ content: 'hi', mode: 'chat', thinking_effort: 'high' }, (event) => events.push(event.type))
    expect(events).toEqual(['message.delta', 'completed'])
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toMatchObject({ thinking_effort: 'high' })
    vi.unstubAllGlobals()
  })
})

