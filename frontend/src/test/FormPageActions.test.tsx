import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { EnvironmentProvider } from '../environment'
import { ApiError } from '../api'
import { FormPage, validationErrorsFromApi } from '../pages/FormPage'
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
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

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

  it('extracts field errors from a rejected submit response', () => {
    const reason = new ApiError(422, 'Форма не прошла валидацию', {
      detail: {
        validation: {
          errors: [{ field: 'context_path', code: 'domain_validation', message: 'Некорректный путь' }],
        },
      },
    })
    expect(validationErrorsFromApi(reason)).toEqual([
      { field: 'context_path', code: 'domain_validation', message: 'Некорректный путь' },
    ])
  })

  it('shows validation beside the field and navigates to the first error', async () => {
    const user = userEvent.setup()
    const fieldDocument: FormDocument = {
      ...document,
      itsm_support: false,
      custom_actions: [],
      fields: [{
        key: 'name', path: 'name', label: 'Название API', type: 'text', required: true,
        visible: true, dynamic: false, placeholder: '', default: '', hint: '',
        file_type: '', width: 1, plural: false, plural_max: null,
        depends_on: null, depends_on_field: null,
      }],
      initial_values: { name: '' },
    }
    const scrollIntoView = vi.fn()
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: scrollIntoView,
    })
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith('/preview')) {
        return new Response(JSON.stringify({
          valid: false,
          values: { name: '' },
          errors: [{ field: 'name', code: 'required', message: 'Поле обязательно' }],
          visible_fields: ['name'],
        }), { status: 200, headers: { 'content-type': 'application/json' } })
      }
      return new Response(JSON.stringify(fieldDocument), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      })
    }))

    render(
      <MemoryRouter initialEntries={['/forms/api.create']}>
        <EnvironmentProvider>
          <Routes>
            <Route path="/forms/:formId" element={<FormPage />} />
          </Routes>
        </EnvironmentProvider>
      </MemoryRouter>,
    )

    await user.click(await screen.findByRole('button', { name: /Отправить/ }))
    const input = screen.getByRole('textbox', { name: /Название API/ })
    await waitFor(() => expect(input).toHaveFocus())
    expect(scrollIntoView).toHaveBeenCalledWith({ behavior: 'smooth', block: 'center' })
    expect(input.closest('.form-field')).toHaveClass('invalid')
    expect(screen.getByRole('alert')).toHaveTextContent('Поле обязательно')
  })
})
