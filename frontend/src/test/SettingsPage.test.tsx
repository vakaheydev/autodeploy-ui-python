import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { SettingsPage } from '../pages/SettingsPage'

const settings = {
  groups: [{ name: 'Доступ', fields: [{
    key: 'TFS_TOKEN', label: 'TFS token', group: 'Доступ', kind: 'secret', default: '',
    description: '', required: false, restart_required: false, minimum: null, maximum: null,
    configured: true, value: null,
  }] }],
}

describe('SettingsPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('keeps saved secrets write-only and sends only an explicit replacement', async () => {
    const fetch = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => new Response(
      JSON.stringify(settings), { status: 200, headers: { 'content-type': 'application/json' } },
    ))
    vi.stubGlobal('fetch', fetch)
    const user = userEvent.setup()
    render(<MemoryRouter><SettingsPage /></MemoryRouter>)
    const token = await screen.findByLabelText(/TFS token/)
    expect(token).toHaveAttribute('placeholder', expect.stringContaining('настроено'))
    expect(screen.queryByRole('button', { name: /Сохранить настройки/ })).not.toBeInTheDocument()
    await user.type(token, 'new-token')
    expect(token.closest('.configuration-field')).toHaveClass('changed')
    expect(screen.getByRole('button', { name: /Сохранить настройки/ })).toBeVisible()
    await user.click(screen.getByRole('button', { name: /Сохранить настройки/ }))
    const call = fetch.mock.calls.find(([, init]) => init?.method === 'PUT')
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({ values: { TFS_TOKEN: 'new-token' }, clear: [] })
    await waitFor(() => expect(screen.queryByRole('button', { name: /Сохранить настройки/ })).not.toBeInTheDocument())

    await user.type(token, 'another-token')
    await user.click(screen.getByRole('button', { name: /Сбросить правки/ }))
    expect(token).toHaveValue('')
    expect(screen.queryByRole('button', { name: /Сохранить настройки/ })).not.toBeInTheDocument()
  })

  it('opens OpenCode Server management inside the OpenCode settings section', async () => {
    const document = { groups: [
      ...settings.groups,
      { name: 'OpenCode', fields: [{
        key: 'OPENCODE_SERVER_URL', label: 'Адрес сервера', group: 'OpenCode', kind: 'text', default: 'http://127.0.0.1:4096',
        description: '', required: true, restart_required: false, minimum: null, maximum: null, configured: true, value: 'http://127.0.0.1:4096',
      }] },
    ] }
    const status = { state: 'ready', message: 'Подключено', version: '1.18.18', address: 'http://127.0.0.1:4096', pid: null, agent_loaded: true, ownership: 'external', runtime_dir: '' }
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input)
      const payload = path.includes('/opencode/status') ? status : path.includes('/opencode/mcp') ? { connected: true, items: [] } : document
      return new Response(JSON.stringify(payload), { status: 200, headers: { 'content-type': 'application/json' } })
    }))

    render(<MemoryRouter initialEntries={['/settings?section=OpenCode']}><SettingsPage /></MemoryRouter>)

    expect(await screen.findByRole('heading', { name: 'OpenCode Server' })).toBeVisible()
    expect(screen.getByText('http://127.0.0.1:4096 · OpenCode 1.18.18')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Подключиться' })).toBeVisible()
    expect(screen.getByLabelText(/Адрес сервера/)).toHaveValue('http://127.0.0.1:4096')
  })
})
