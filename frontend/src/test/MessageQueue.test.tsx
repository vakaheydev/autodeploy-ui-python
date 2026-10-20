import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Copilot } from '../components/Copilot'
import { EnvironmentProvider } from '../environment'

class Events {
  static current: Events
  onmessage: ((event: MessageEvent) => void) | null = null
  close = vi.fn()
  constructor() { Events.current = this }
  emit(kind: string, payload: unknown, sequence: number) {
    this.onmessage?.({ data: JSON.stringify({ kind, payload, sequence, timestamp: Date.now() / 1000 }) } as MessageEvent)
  }
}

function mount(overrides: Record<string, unknown> = {}, reject = false) {
  const state = {
    id: 'chat', title: 'Диалог', busy: true, provider_id: 'corp', model_id: 'model',
    variants: ['none'], default_variant: 'none', tokens_used: 0, context_limit: 32000,
    generation_started_at: Date.now() / 1000, opencode_url: null, events: [],
    queue_supported: true, queue_enabled: true, queue_ready: true, queue_limit: 10,
    queue_paused: false, active_environment: 'test_int', queue: [] as Record<string, unknown>[],
    ...overrides,
  }
  window.localStorage.setItem('autodeploy.ai.session', 'chat')
  Object.defineProperty(HTMLElement.prototype, 'scrollTo', { value: vi.fn(), configurable: true })
  vi.stubGlobal('EventSource', Events)
  const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
  const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (path.endsWith('/messages')) {
      if (reject) return json({ detail: 'Очередь недоступна' }, 409)
      state.queue.push({ id: 'msg_1', message: JSON.parse(String(init?.body)).message, environment: 'test_int', model_id: 'model', thinking: 'none' })
      Events.current.emit('queue', state, 1)
      return json({ queued: true, queue_id: 'msg_1' }, 202)
    }
    if (path.endsWith('/queue/msg_1') && init?.method === 'DELETE') { state.queue = []; return json(state) }
    if (path.endsWith('/queue/resume')) return json({ job_id: 'job' }, 202)
    if (path.endsWith('/queue') || path.endsWith('/chat')) return json(state)
    if (path.endsWith('/opencode/models')) return json({ items: [{ provider_id: 'corp', model_id: 'model', model_name: 'Model', variants: ['none'] }] })
    if (path.endsWith('/ai/sessions')) return json({ items: [{ ...state, updated_at: 1 }] })
    throw new Error(path)
  })
  vi.stubGlobal('fetch', fetch)
  render(<MemoryRouter><EnvironmentProvider><Copilot /></EnvironmentProvider></MemoryRouter>)
  return { state, fetch, user: userEvent.setup() }
}

afterEach(() => { window.localStorage.clear(); vi.unstubAllGlobals() })

describe('Native OpenCode queue', () => {
  it('submits while generating, shows server inbox and removes a pending message', async () => {
    const { user, fetch } = mount()
    await screen.findByRole('button', { name: 'В очередь' })
    await user.type(screen.getByRole('textbox'), 'Следующая задача{Enter}')
    const queue = await screen.findByRole('region', { name: 'Очередь сообщений' })
    expect(within(queue).getByText('Следующая задача')).toBeVisible()
    expect(screen.getByRole('textbox')).toHaveValue('')
    expect(screen.getByRole('button', { name: 'Остановить' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Модель' })).toBeDisabled()
    await user.click(within(queue).getByRole('button', { name: 'Убрать сообщение 1 из очереди' }))
    await waitFor(() => expect(screen.queryByRole('region', { name: 'Очередь сообщений' })).not.toBeInTheDocument())
    expect(fetch).toHaveBeenCalledWith('/api/v1/ai/sessions/chat/queue/msg_1', expect.objectContaining({ method: 'DELETE' }))
  })

  it('retains text on queue error and does not stop the active response', async () => {
    const { user } = mount({}, true)
    await screen.findByRole('button', { name: 'В очередь' })
    await user.type(screen.getByRole('textbox'), 'Не потерять{Enter}')
    expect(await screen.findByText('Очередь недоступна')).toBeVisible()
    expect(screen.getByRole('textbox')).toHaveValue('Не потерять')
    expect(screen.getByRole('button', { name: 'Остановить' })).toBeVisible()
  })

  it.each([{ queue_supported: false, queue_enabled: false }, { queue_enabled: false }])('does not discard Enter while sending is unavailable: %j', async (overrides) => {
    const { user, fetch } = mount(overrides)
    await screen.findByRole('button', { name: 'Отправить' })
    await user.type(screen.getByRole('textbox'), 'Черновик{Enter}')
    expect(screen.getByRole('textbox')).toHaveValue('Черновик')
    expect(fetch.mock.calls.some(([path]) => String(path).endsWith('/messages'))).toBe(false)
  })

  it('restores pending items and resumes the native queue without sending a new message', async () => {
    const { user, fetch, state } = mount({ busy: false, queue_paused: true, queue: [
      { id: 'msg_1', message: 'Сохранённое сообщение', environment: 'test_int', model_id: 'model', thinking: 'none' },
    ] })
    expect(await screen.findByText('Сохранённое сообщение')).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Продолжить очередь' }))
    expect(fetch.mock.calls.some(([path]) => String(path).endsWith('/queue/resume'))).toBe(true)
    expect(fetch.mock.calls.some(([path]) => String(path).endsWith('/messages'))).toBe(false)
    act(() => Events.current.emit('queue', { ...state, queue: [], queue_paused: false }, 5))
    expect(screen.queryByRole('region', { name: 'Очередь сообщений' })).not.toBeInTheDocument()
  })
})
