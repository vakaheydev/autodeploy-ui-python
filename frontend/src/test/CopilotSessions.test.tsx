import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Copilot } from '../components/Copilot'
import { EnvironmentProvider } from '../environment'

const snapshot = (id: string) => ({
  id,
  busy: false,
  provider_id: 'corp',
  model_id: 'model',
  default_variant: 'none',
  variants: ['none', 'low'],
  opencode_url: null,
  events: [],
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
})
