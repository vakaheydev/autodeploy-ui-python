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
    if (path.endsWith('/queue/reorder')) {
      const ids = JSON.parse(String(init?.body)).message_ids as string[]
      state.queue = ids.map(id => state.queue.find(item => item.id === id)!)
      return json(state)
    }
    if (path.endsWith('/send')) {
      state.queue = state.queue.filter(item => !path.endsWith(`/queue/${item.id}/send`))
      return json(state)
    }
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
  it('does not show a queue during ordinary generation without follow-ups', async () => {
    const { state } = mount()
    await screen.findByRole('button', { name: 'Остановить' })
    expect(screen.queryByRole('region', { name: 'Очередь сообщений' })).not.toBeInTheDocument()
    act(() => Events.current.emit('queue', { ...state, queue: [] }, 1))
    expect(screen.queryByText('Сообщение из OpenCode')).not.toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Очередь сообщений' })).not.toBeInTheDocument()
  })

  it('does not reactivate old permission cards in the next turn', async () => {
    mount({ events: [
      { sequence: 1, timestamp: 1, kind: 'agent_event', payload: { kind: 'permission', permission_id: 'old', title: 'Old permission' } },
      { sequence: 2, timestamp: 2, kind: 'idle', payload: {} },
      { sequence: 3, timestamp: 3, kind: 'progress', payload: { text: 'New turn' } },
    ] })
    expect(await screen.findByText('Запрос больше не ожидает ответа')).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Разрешить один раз' })).not.toBeInTheDocument()
  })

  it('closes a live permission card on an external resolution event', async () => {
    mount({ events: [
      { sequence: 1, timestamp: 1, kind: 'agent_event', payload: { kind: 'permission', permission_id: 'per_live', title: 'Permission' } },
    ] })
    expect(await screen.findByRole('button', { name: 'Разрешить один раз' })).toBeEnabled()
    act(() => Events.current.emit('agent_event', { kind: 'permission_resolved', permission_id: 'per_live', detail: 'processed' }, 2))
    expect(screen.queryByRole('button', { name: 'Разрешить один раз' })).not.toBeInTheDocument()
    expect(screen.getByText('Запрос больше не ожидает ответа')).toBeVisible()
  })

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

  it('sends a composer draft immediately using steer and retains it on failure', async () => {
    const { user, fetch } = mount({}, true)
    await user.type(await screen.findByRole('textbox'), 'Срочное уточнение')
    await user.click(screen.getByRole('button', { name: 'Отправить сейчас' }))
    const request = fetch.mock.calls.find(([path]) => String(path).endsWith('/messages'))!
    expect(JSON.parse(String(request[1]?.body))).toMatchObject({ message: 'Срочное уточнение', delivery: 'steer' })
    expect(await screen.findByText('Очередь недоступна')).toBeVisible()
    expect(screen.getByRole('textbox')).toHaveValue('Срочное уточнение')
    expect(fetch.mock.calls.some(([path]) => String(path).endsWith('/cancel'))).toBe(false)
  })

  it('shows a concise queue, changes server order and sends an individual item now', async () => {
    const { user, fetch } = mount({ queue: [
      { id: 'msg_1', message: 'Первая', environment: 'test_int', model_id: 'model', thinking: 'none' },
      { id: 'msg_2', message: 'Вторая', environment: 'test_int', model_id: 'model', thinking: 'none' },
    ] })
    const queue = await screen.findByRole('region', { name: 'Очередь сообщений' })
    expect(queue).not.toHaveTextContent('Далее в диалоге')
    expect(queue).not.toHaveTextContent('OpenCode выполнит')
    expect(queue).not.toHaveTextContent('Thinking:')
    expect(within(queue).getByRole('button', { name: 'Переместить сообщение 1 выше' })).toBeDisabled()
    expect(within(queue).getByRole('button', { name: 'Переместить сообщение 2 ниже' })).toBeDisabled()
    await user.click(within(queue).getByRole('button', { name: 'Переместить сообщение 2 выше' }))
    await waitFor(() => expect(within(queue).getAllByRole('listitem')[0]).toHaveTextContent('Вторая'))
    const request = fetch.mock.calls.find(([path]) => String(path).endsWith('/queue/reorder'))!
    expect(JSON.parse(String(request[1]?.body))).toEqual({ message_ids: ['msg_2', 'msg_1'] })
    await user.click(within(queue).getByRole('button', { name: 'Отправить сообщение 1 сейчас' }))
    await waitFor(() => expect(within(queue).getAllByRole('listitem')).toHaveLength(1))
    expect(fetch.mock.calls.some(([path]) => String(path).endsWith('/queue/msg_2/send'))).toBe(true)
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
