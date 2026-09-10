import { render, screen, waitFor, within } from '@testing-library/react'
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

  it('shows a 422 validation error beside the setting that caused it', async () => {
    vi.stubGlobal('fetch', vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        return new Response(JSON.stringify({
          detail: { message: 'TFS token: значение отклонено сервером', fields: ['TFS_TOKEN'] },
        }), { status: 422, headers: { 'content-type': 'application/json' } })
      }
      return new Response(JSON.stringify(settings), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      })
    }))
    const user = userEvent.setup()
    render(<MemoryRouter><SettingsPage /></MemoryRouter>)

    const token = await screen.findByLabelText(/TFS token/)
    await user.type(token, 'invalid-token')
    await user.click(screen.getByRole('button', { name: /Сохранить настройки/ }))

    const field = token.closest('.configuration-field') as HTMLElement
    expect(field).toHaveClass('invalid')
    expect(await within(field).findByRole('alert')).toHaveTextContent('значение отклонено сервером')
    expect(screen.getAllByRole('alert')).toHaveLength(1)

    await user.type(token, '-fixed')
    expect(within(field).queryByRole('alert')).not.toBeInTheDocument()
    expect(field).not.toHaveClass('invalid')
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

  it('selects the OpenCode log level from server-declared choices', async () => {
    const document = { groups: [{ name: 'OpenCode', fields: [{
      key: 'AUTODEPLOY_OPENCODE_LOG_LEVEL', label: 'Уровень логирования OpenCode', group: 'OpenCode', kind: 'select', default: 'INFO',
      choices: ['OFF', 'ERROR', 'WARNING', 'INFO', 'DEBUG'], description: '', required: true, restart_required: false,
      minimum: null, maximum: null, configured: true, value: 'INFO',
    }] }] }
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (path.includes('/opencode/status')) return new Response(JSON.stringify({ state: 'stopped', message: '', version: '', address: '', pid: null, agent_loaded: false, ownership: 'none', runtime_dir: '' }), { status: 200, headers: { 'content-type': 'application/json' } })
      if (path.includes('/opencode/mcp')) return new Response(JSON.stringify({ connected: false, items: [] }), { status: 200, headers: { 'content-type': 'application/json' } })
      return new Response(JSON.stringify(document), { status: 200, headers: { 'content-type': 'application/json' } })
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<MemoryRouter initialEntries={['/settings?section=OpenCode']}><SettingsPage /></MemoryRouter>)

    await user.click(await screen.findByRole('button', { name: 'Уровень логирования OpenCode' }))
    await user.click(screen.getByRole('option', { name: 'OFF' }))
    await user.click(screen.getByRole('button', { name: 'Сохранить настройки' }))

    const request = fetchMock.mock.calls.find(([, init]) => init?.method === 'PUT')
    expect(JSON.parse(String(request?.[1]?.body))).toEqual({ values: { AUTODEPLOY_OPENCODE_LOG_LEVEL: 'OFF' }, clear: [] })
  })

  it('edits ticket-type prompts as typed server-side settings', async () => {
    const promptSettings = {
      rules: [{ ticket_type: 'create_api_v2', prompt: 'Use service_name as name.' }],
      warning: '', max_rules: 100, max_ticket_type_chars: 200, max_prompt_chars: 16000,
      precedence: 'ui_override_then_corporate_hook',
    }
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (path.endsWith('/opencode/mcp')) return new Response(JSON.stringify({ connected: false, items: [] }), { status: 200, headers: { 'content-type': 'application/json' } })
      if (path.endsWith('/settings/itsm-ai-prompts')) {
        if (init?.method === 'PUT') {
          const body = JSON.parse(String(init.body))
          return new Response(JSON.stringify({ ...promptSettings, rules: body.rules }), { status: 200, headers: { 'content-type': 'application/json' } })
        }
        return new Response(JSON.stringify(promptSettings), { status: 200, headers: { 'content-type': 'application/json' } })
      }
      return new Response(JSON.stringify(settings), { status: 200, headers: { 'content-type': 'application/json' } })
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<MemoryRouter initialEntries={['/settings?section=ITSM%20%D0%B8%20AI']}><SettingsPage /></MemoryRouter>)

    const prompt = await screen.findByLabelText('Prompt для AI 1')
    await user.clear(prompt)
    await user.type(prompt, 'Use requested_api.contextPath.')
    expect(prompt.closest('.itsm-prompt-card')).toHaveClass('changed')
    await user.click(screen.getByRole('button', { name: 'Сохранить ITSM AI-правила' }))

    const request = fetchMock.mock.calls.find(([input, init]) => String(input).endsWith('/settings/itsm-ai-prompts') && init?.method === 'PUT')
    expect(JSON.parse(String(request?.[1]?.body))).toEqual({
      rules: [{ ticket_type: 'create_api_v2', prompt: 'Use requested_api.contextPath.' }],
    })
    expect(await screen.findByText(/Правила сохранены/)).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Сохранить ITSM AI-правила' })).not.toBeInTheDocument()
  })

  it('saves fail-closed AI visibility and an explicit policy per plugin operation', async () => {
    const policy = {
      ai_visible: false,
      requires_new_session: true,
      plugins: [{
        id: 'reports.capacity', title: 'Capacity report', description: 'Отчёт по нагрузке',
        visible: false,
        operations: [{
          id: 'recalculate', label: 'Пересчитать', description: 'Обновить отчёт',
          policy: 'deny', tool_name: 'plugin_reports_capacity_recalculate_8cded0a1',
        }],
      }],
    }
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (path.endsWith('/opencode/mcp')) return new Response(JSON.stringify({ connected: false, items: [] }), { status: 200, headers: { 'content-type': 'application/json' } })
      if (path.endsWith('/plugins/ai-policy')) {
        if (init?.method === 'PUT') {
          const body = JSON.parse(String(init.body))
          return new Response(JSON.stringify({
            ...policy,
            ai_visible: body.ai_visible,
            plugins: policy.plugins.map((plugin) => ({
              ...plugin,
              visible: body.plugins[0].visible,
              operations: plugin.operations.map((operation) => ({
                ...operation, policy: body.plugins[0].operations[operation.id],
              })),
            })),
          }), { status: 200, headers: { 'content-type': 'application/json' } })
        }
        return new Response(JSON.stringify(policy), { status: 200, headers: { 'content-type': 'application/json' } })
      }
      return new Response(JSON.stringify(settings), { status: 200, headers: { 'content-type': 'application/json' } })
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<MemoryRouter initialEntries={['/settings?section=Плагины']}><SettingsPage /></MemoryRouter>)

    await user.click(await screen.findByRole('checkbox', { name: 'ИИ видит плагины' }))
    await user.click(screen.getByRole('checkbox', { name: 'ИИ видит плагин Capacity report' }))
    await user.click(screen.getByRole('button', { name: 'Политика Пересчитать' }))
    await user.click(screen.getByRole('option', { name: /Manual approve/ }))
    await user.click(screen.getByRole('button', { name: 'Сохранить AI-политику' }))

    const request = fetchMock.mock.calls.find(([input, init]) => String(input).endsWith('/plugins/ai-policy') && init?.method === 'PUT')
    expect(JSON.parse(String(request?.[1]?.body))).toEqual({
      ai_visible: true,
      plugins: [{ id: 'reports.capacity', visible: true, operations: { recalculate: 'manual' } }],
    })
    expect(await screen.findByText(/Создайте новый AI-чат/)).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Сохранить AI-политику' })).not.toBeInTheDocument()
  })
})
