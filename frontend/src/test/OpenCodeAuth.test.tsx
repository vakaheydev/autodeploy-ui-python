import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { OpenCodeProvider, useOpenCode } from '../opencode'
import { OpenCodeServerPanel } from '../components/OpenCodeServerPanel'

function Refresh() {
  const { refresh } = useOpenCode()
  return <button onClick={() => void refresh()}>Обновить статус</button>
}

describe('OpenCode password recovery', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('opens globally, stays dismissed through polling, retries in settings and reopens for a new 401', async () => {
    let status = { state: 'error', auth_required: true, address: 'http://127.0.0.1:4096', message: 'HTTP 401' }
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'POST') {
        if (JSON.parse(String(init.body)).password === 'correct-password') {
          status = { ...status, state: 'ready', auth_required: false, message: 'Подключено' }
        }
      }
      return new Response(JSON.stringify(status), { headers: { 'content-type': 'application/json' } })
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<OpenCodeProvider><OpenCodeServerPanel /><Refresh /></OpenCodeProvider>)
    const dialog = await screen.findByRole('dialog', { name: 'Вход в OpenCode' })
    await user.click(within(dialog).getByRole('button', { name: 'Закрыть' }))
    await user.click(screen.getByRole('button', { name: 'Обновить статус' }))
    await act(async () => {})
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    const password = screen.getByLabelText('Пароль OpenCode Server')
    expect(password).toHaveAttribute('type', 'password')
    await user.type(password, 'wrong-password')
    await user.click(screen.getByRole('button', { name: 'Сохранить и подключиться' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('HTTP 401')
    expect(password).toHaveValue('')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    await user.type(password, 'correct-password')
    await user.click(screen.getByRole('button', { name: 'Сохранить и подключиться' }))
    await waitFor(() => expect(screen.queryByLabelText('Пароль OpenCode Server')).not.toBeInTheDocument())
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(2)
    status = { ...status, state: 'error', auth_required: true }
    await user.click(screen.getByRole('button', { name: 'Обновить статус' }))
    expect(await screen.findByRole('dialog')).toBeVisible()
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('keeps the dialog dismissible during a pending login', async () => {
    let resolveLogin!: (response: Response) => void
    vi.stubGlobal('fetch', vi.fn((_, init?: RequestInit) => init?.method === 'POST'
      ? new Promise<Response>((resolve) => { resolveLogin = resolve })
      : Promise.resolve(new Response(JSON.stringify({ auth_required: true, address: 'localhost', state: 'error' }), { headers: { 'content-type': 'application/json' } }))))
    const user = userEvent.setup()
    render(<OpenCodeProvider><OpenCodeServerPanel /></OpenCodeProvider>)
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText('Пароль OpenCode Server'), 'correct-password')
    await user.click(within(dialog).getByRole('button', { name: 'Сохранить и подключиться' }))
    await user.click(within(dialog).getByRole('button', { name: 'Закрыть' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Пароль OpenCode Server')).toBeVisible()
    await act(async () => resolveLogin(new Response(JSON.stringify({ state: 'ready', auth_required: false }), { headers: { 'content-type': 'application/json' } })))
    expect(screen.queryByLabelText('Пароль OpenCode Server')).not.toBeInTheDocument()
  })
})
