import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { EnvironmentProvider } from '../environment'
import { FormsPage } from '../pages/FormsPage'

describe('FormsPage search', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('matches keywords originating from Python field descriptions', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => new Response(JSON.stringify(String(input).endsWith('/api/v1/drafts') ? { items: [] } : {
      environments: [{ key: 'test_int', label: 'Test Internal' }],
      categories: [{ id: 'api', label: 'API', forms: [
        { id: 'api.create', title: 'Создание API', category: 'api', category_label: 'API', version: '1', field_count: 4, confirm_submit: false, itsm_support: false, keywords: ['context path', 'владелец'] },
        { id: 'api.delete', title: 'Удаление API', category: 'api', category_label: 'API', version: '1', field_count: 1, confirm_submit: true, itsm_support: false, keywords: ['удалить'] },
      ] }],
    }), { status: 200, headers: { 'content-type': 'application/json' } })))
    const user = userEvent.setup()
    render(<MemoryRouter><EnvironmentProvider><FormsPage /></EnvironmentProvider></MemoryRouter>)
    await screen.findByText('Создание API')
    await user.type(screen.getByRole('textbox', { name: 'Поиск форм' }), 'context path')
    expect(screen.getByText('Создание API')).toBeInTheDocument()
    expect(screen.queryByText('Удаление API')).not.toBeInTheDocument()
  })

  it('shows persistent AI and manual drafts and deletes them explicitly', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (init?.method === 'DELETE') return new Response(null, { status: 204 })
      if (path.endsWith('/api/v1/drafts')) return new Response(JSON.stringify({ items: [{
        id: 'draft-1', form_id: 'api.create', title: 'Создание API', environment: 'test_int',
        form_version: '1', revision: 2, source: 'ai', created_at: 100, updated_at: 200,
        valid: true, stale: false, review_count: 3,
      }] }), { status: 200, headers: { 'content-type': 'application/json' } })
      return new Response(JSON.stringify({ environments: [], categories: [] }), { status: 200, headers: { 'content-type': 'application/json' } })
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<MemoryRouter><EnvironmentProvider><FormsPage /></EnvironmentProvider></MemoryRouter>)

    await user.click(await screen.findByRole('tab', { name: /Черновики/ }))
    expect(await screen.findByText('Черновик Copilot')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Создание API/ })).toHaveAttribute('href', '/forms/api.create?draft=draft-1')
    await user.click(screen.getByRole('button', { name: 'Удалить черновик Создание API' }))
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/drafts/draft-1', expect.objectContaining({ method: 'DELETE' }))
  })
})
