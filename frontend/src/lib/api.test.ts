import { describe, expect, it, vi } from 'vitest'

import { runsApi, streamChat } from './api'

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

describe('runsApi', () => {
  it('sends a research topic revision as a command input', async () => {
    const body = new ReadableStream({
      start(controller) {
        controller.close()
      },
    })
    const fetchMock = vi.fn().mockResolvedValue(new Response(body, { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await runsApi.command('run-1', 'revise', () => undefined, undefined, '缩小研究范围')

    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      action: 'revise',
      input: '缩小研究范围',
    })
    vi.unstubAllGlobals()
  })

  it('renders structured validation errors as readable text', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: [{ msg: '研究主题对话不能为空' }] }), {
        status: 422,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(runsApi.command('run-1', 'revise', () => undefined)).rejects.toThrow(
      '研究主题对话不能为空',
    )
    vi.unstubAllGlobals()
  })
})

