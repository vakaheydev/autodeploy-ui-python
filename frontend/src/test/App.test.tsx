import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from '../App'

const catalog = {
  environments: [{ key: 'test_int', label: 'Test Internal' }],
  categories: [{ id: 'api', label: 'API', forms: [{ id: 'api.create', title: 'Создание API', category: 'api', category_label: 'API', version: 'abc', field_count: 6, confirm_submit: false, itsm_support: false }] }],
}

describe('App shell', () => {
  beforeEach(() => {
    window.localStorage.clear()
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input)
      const payload = path.includes('/opencode/status')
        ? { state: 'stopped', address: '', message: 'Отключён' }
        : catalog
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
})
