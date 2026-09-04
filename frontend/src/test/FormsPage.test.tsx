import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { EnvironmentProvider } from '../environment'
import { FormsPage } from '../pages/FormsPage'

describe('FormsPage search', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('matches keywords originating from Python field descriptions', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
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
})
