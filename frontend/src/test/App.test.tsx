import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from '../App'

const catalog = {
  environments: [
    { key: 'test_int', label: 'Test Internal' },
    { key: 'prod_int', label: 'Prod Internal' },
  ],
  categories: [{ id: 'api', label: 'API', forms: [{ id: 'api.create', title: 'Создание API', category: 'api', category_label: 'API', version: 'abc', field_count: 6, confirm_submit: false, itsm_support: false }] }],
}

describe('App shell', () => {
  beforeEach(() => {
    window.localStorage.clear()
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      let payload: unknown = catalog
      if (path.includes('/opencode/status')) {
        payload = { state: 'stopped', address: '', message: 'Отключён' }
      } else if (path.includes('/environments/activate')) {
        const body = JSON.parse(String(init?.body)) as { previous_environment: string | null; environment: string }
        payload = { ...body, changed: true, hook_configured: true }
      }
      return new Response(JSON.stringify(payload), { status: 200, headers: { 'content-type': 'application/json' } })
    }))
  })
  afterEach(() => vi.unstubAllGlobals())

  it('renders the modern shell and Python-backed modules', async () => {
    render(<MemoryRouter><App /></MemoryRouter>)
    expect(await screen.findByRole('heading', { name: 'Gravitee AutoDeploy' })).toBeInTheDocument()
    expect(screen.queryByText('Единое рабочее пространство')).not.toBeInTheDocument()
    expect(screen.queryByText(/Формы, справочники, поиск и AI-помощник/)).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Формы/ })).toBeInTheDocument()
    await waitFor(() => expect(fetch).toHaveBeenCalled())
  })

  it('switches and persists the dark theme', async () => {
    const user = userEvent.setup()
    render(<MemoryRouter><App /></MemoryRouter>)
    await user.click(screen.getByRole('button', { name: 'Включить тёмную тему' }))
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(window.localStorage.getItem('autodeploy.theme')).toBe('dark')
  })

  it('activates the server hook before committing an environment switch', async () => {
    const user = userEvent.setup()
    render(<MemoryRouter><App /></MemoryRouter>)
    await screen.findByRole('heading', { name: 'Gravitee AutoDeploy' })

    await user.click(screen.getByRole('button', { name: 'Окружение' }))
    await user.click(screen.getByRole('option', { name: 'Prod Internal' }))

    await waitFor(() => expect(window.localStorage.getItem('autodeploy.environment')).toBe('prod_int'))
    const activationCall = vi.mocked(fetch).mock.calls.find(([input]) => String(input).includes('/environments/activate'))
    expect(activationCall).toBeDefined()
    expect(JSON.parse(String(activationCall?.[1]?.body))).toEqual({
      previous_environment: 'test_int',
      environment: 'prod_int',
    })
  })

  it('keeps the previous environment and shows a hook rejection by the selector', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input)
      if (path.includes('/environments/activate')) {
        return new Response(JSON.stringify({ detail: { message: 'Корпоративная подготовка не выполнена' } }), { status: 422, headers: { 'content-type': 'application/json' } })
      }
      const payload = path.includes('/opencode/status')
        ? { state: 'stopped', address: '', message: 'Отключён' }
        : catalog
      return new Response(JSON.stringify(payload), { status: 200, headers: { 'content-type': 'application/json' } })
    }))
    render(<MemoryRouter><App /></MemoryRouter>)
    await screen.findByRole('heading', { name: 'Gravitee AutoDeploy' })

    await user.click(screen.getByRole('button', { name: 'Окружение' }))
    await user.click(screen.getByRole('option', { name: 'Prod Internal' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Корпоративная подготовка не выполнена')
    expect(window.localStorage.getItem('autodeploy.environment')).toBeNull()
    expect(screen.getByRole('button', { name: 'Окружение' })).toHaveTextContent('Test Internal')
  })
})
