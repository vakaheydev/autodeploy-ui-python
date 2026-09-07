import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { EnvironmentProvider } from '../environment'
import { FormPage } from '../pages/FormPage'
import type { FormDocument } from '../types'

const document: FormDocument = {
  id: 'api.create',
  title: 'Создание API',
  category: 'api',
  category_label: 'API',
  version: 'version-1',
  confirm_submit: false,
  itsm_support: true,
  http_method: 'POST',
  fields: [],
  initial_values: {},
  custom_actions: [{
    id: 'load-tfs',
    label: 'Загрузить из TFS',
    available: true,
    reason: '',
    style: 'Secondary',
    confirmation_required: false,
  }],
}

describe('FormPage custom actions', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('places server actions in the common form action bar', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(document), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    })))

    render(
      <MemoryRouter initialEntries={['/forms/api.create']}>
        <EnvironmentProvider>
          <Routes>
            <Route path="/forms/:formId" element={<FormPage />} />
          </Routes>
        </EnvironmentProvider>
      </MemoryRouter>,
    )

    const customAction = await screen.findByRole('button', { name: 'Загрузить из TFS' })
    const commonActions = customAction.closest('.form-actions-secondary')

    expect(commonActions).not.toBeNull()
    expect(commonActions).toContainElement(screen.getByRole('button', { name: /Просмотр JSON/ }))
    expect(commonActions).toContainElement(screen.getByRole('button', { name: /Подтянуть заявку/ }))
    expect(screen.queryByText('Дополнительные действия')).not.toBeInTheDocument()
    expect(screen.queryByText('api.create')).not.toBeInTheDocument()
    expect(screen.queryByText(/версия схемы/)).not.toBeInTheDocument()
    expect(screen.queryByText('Python runtime')).not.toBeInTheDocument()
  })
})
