import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
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
    render(<SettingsPage />)
    const token = await screen.findByLabelText(/TFS token/)
    expect(token).toHaveAttribute('placeholder', expect.stringContaining('настроено'))
    await user.type(token, 'new-token')
    expect(token.closest('.configuration-field')).toHaveClass('changed')
    await user.click(screen.getByRole('button', { name: /Сохранить настройки/ }))
    const call = fetch.mock.calls.find(([, init]) => init?.method === 'PUT')
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({ values: { TFS_TOKEN: 'new-token' }, clear: [] })
  })
})
