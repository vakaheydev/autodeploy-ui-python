import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Copilot } from '../components/Copilot'
import { EnvironmentProvider } from '../environment'

const snapshot = (id: string, overrides: Record<string, unknown> = {}) => ({
  id,
  title: id === 'chat-1' ? 'Первый диалог' : 'Второй диалог',
  busy: false,
  provider_id: 'corp',
  model_id: 'model',
  default_variant: 'none',
  variants: ['none', 'low'],
  tokens_used: 1250,
  context_limit: 131072,
  generation_started_at: null,
  opencode_url: null,
  events: [],
  ...overrides,
})

class EventSourceStub {
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: (() => void) | null = null
  close = vi.fn()
}

describe('Copilot sessions', () => {
  afterEach(() => {
    window.localStorage.clear()
    vi.unstubAllGlobals()
  })

  it('deletes the current session after confirmation and switches to the next one', async () => {
    window.localStorage.setItem('autodeploy.ai.session', 'chat-1')
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { value: vi.fn(), configurable: true })
    vi.stubGlobal('EventSource', EventSourceStub)
    const sessions = [
      { id: 'chat-1', title: 'Первый диалог', updated_at: 20, busy: false, provider_id: 'corp', model_id: 'model', opencode_session_id: 'ses-1' },
      { id: 'chat-2', title: 'Второй диалог', updated_at: 10, busy: false, provider_id: 'corp', model_id: 'model', opencode_session_id: 'ses-2' },
    ]
    const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (init?.method === 'DELETE' && path.endsWith('/chat-1')) return new Response(null, { status: 204 })
      if (path.endsWith('/chat-1')) return new Response(JSON.stringify(snapshot('chat-1')), { status: 200, headers: { 'content-type': 'application/json' } })
      if (path.endsWith('/chat-2')) return new Response(JSON.stringify(snapshot('chat-2')), { status: 200, headers: { 'content-type': 'application/json' } })
      if (path.endsWith('/opencode/models')) return new Response(JSON.stringify({ items: [{ provider_id: 'corp', model_id: 'model', provider_name: 'Corp', model_name: 'Model', variants: ['none', 'low'] }] }), { status: 200, headers: { 'content-type': 'application/json' } })
      if (path.endsWith('/ai/sessions')) return new Response(JSON.stringify({ items: sessions }), { status: 200, headers: { 'content-type': 'application/json' } })
      throw new Error(`Unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', fetch)
    const user = userEvent.setup()

    render(<MemoryRouter><EnvironmentProvider><Copilot /></EnvironmentProvider></MemoryRouter>)
    expect(await screen.findByRole('button', { name: 'Сессия Copilot' })).toHaveTextContent('Первый диалог')

    await user.click(screen.getByRole('button', { name: 'Удалить текущую сессию' }))
    const confirmation = screen.getByRole('dialog', { name: 'Удалить сессию?' })
    expect(within(confirmation).getByText('Первый диалог')).toBeVisible()
    await user.click(within(confirmation).getByRole('button', { name: 'Удалить' }))

    await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/v1/ai/sessions/chat-1', expect.objectContaining({ method: 'DELETE' })))
    expect(await screen.findByRole('button', { name: 'Сессия Copilot' })).toHaveTextContent('Второй диалог')
    expect(window.localStorage.getItem('autodeploy.ai.session')).toBe('chat-2')
  })

  it('shows token usage, intermediate model text and keeps the server timer after reload', async () => {
    window.localStorage.setItem('autodeploy.ai.session', 'chat-1')
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { value: vi.fn(), configurable: true })
    vi.stubGlobal('EventSource', EventSourceStub)
    const startedAt = Date.now() / 1000 - 18
    const current = snapshot('chat-1', {
      busy: true,
      generation_started_at: startedAt,
      events: [
        { sequence: 1, kind: 'assistant_note', timestamp: startedAt + 1, payload: { text: '**Получил схему.** Теперь ищу API.', thinking: 'none' } },
        { sequence: 2, kind: 'agent_event', timestamp: startedAt + 2, payload: { kind: 'tool', call_id: 'tool-1', title: 'get_api', status: 'completed', input_detail: '{}', output_detail: '{"id":"api"}' } },
      ],
    })
    const fetch = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input)
      if (path.endsWith('/chat-1')) return new Response(JSON.stringify(current), { status: 200, headers: { 'content-type': 'application/json' } })
      if (path.endsWith('/opencode/models')) return new Response(JSON.stringify({ items: [{ provider_id: 'corp', model_id: 'model', provider_name: 'Corp', model_name: 'Model', variants: ['none'], context_limit: 131072 }] }), { status: 200, headers: { 'content-type': 'application/json' } })
      if (path.endsWith('/ai/sessions')) return new Response(JSON.stringify({ items: [{ id: 'chat-1', title: 'Первый диалог', updated_at: 20, busy: true, provider_id: 'corp', model_id: 'model', opencode_session_id: 'ses-1' }] }), { status: 200, headers: { 'content-type': 'application/json' } })
      throw new Error(`Unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', fetch)

    render(<MemoryRouter><EnvironmentProvider><Copilot /></EnvironmentProvider></MemoryRouter>)

    expect(await screen.findByText('Получил схему.', { exact: false })).toBeVisible()
    expect(screen.getByTitle('Контекст последнего ответа / максимальный контекст модели')).toHaveTextContent('1 250 / 131 072')
    expect(await screen.findByText(/1[7-9] с|2[0-1] с/)).toBeVisible()
  })

  it('renames the current chat through the server and updates the selector', async () => {
    window.localStorage.setItem('autodeploy.ai.session', 'chat-1')
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', { value: vi.fn(), configurable: true })
    vi.stubGlobal('EventSource', EventSourceStub)
    let title = 'Первый диалог'
    const sessionItems = () => [{ id: 'chat-1', title, updated_at: 20, busy: false, provider_id: 'corp', model_id: 'model', opencode_session_id: 'ses-1' }]
    const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (init?.method === 'PATCH' && path.endsWith('/chat-1')) {
        title = (JSON.parse(String(init.body)) as { title: string }).title
        return new Response(JSON.stringify(snapshot('chat-1', { title })), { status: 200, headers: { 'content-type': 'application/json' } })
      }
      if (path.endsWith('/chat-1')) return new Response(JSON.stringify(snapshot('chat-1', { title })), { status: 200, headers: { 'content-type': 'application/json' } })
      if (path.endsWith('/opencode/models')) return new Response(JSON.stringify({ items: [{ provider_id: 'corp', model_id: 'model', provider_name: 'Corp', model_name: 'Model', variants: ['none'], context_limit: 131072 }] }), { status: 200, headers: { 'content-type': 'application/json' } })
      if (path.endsWith('/ai/sessions')) return new Response(JSON.stringify({ items: sessionItems() }), { status: 200, headers: { 'content-type': 'application/json' } })
      throw new Error(`Unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', fetch)
    const user = userEvent.setup()

    render(<MemoryRouter><EnvironmentProvider><Copilot /></EnvironmentProvider></MemoryRouter>)
    await screen.findByRole('button', { name: 'Сессия Copilot' })
    await user.click(screen.getByRole('button', { name: 'Переименовать чат' }))
    const dialog = screen.getByRole('dialog', { name: 'Переименовать чат' })
    const input = within(dialog).getByRole('textbox', { name: 'Короткое название' })
    await user.clear(input)
    await user.type(input, 'Копирование API')
    await user.click(within(dialog).getByRole('button', { name: 'Сохранить' }))

    await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/v1/ai/sessions/chat-1', expect.objectContaining({ method: 'PATCH' })))
    expect(await screen.findByRole('button', { name: 'Сессия Copilot' })).toHaveTextContent('Копирование API')
  })
})
