import { render, screen, waitFor, within } from '@testing-library/react'
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

  it('opens the existing inline review when the ITSM hook selects AI mode', async () => {
    const user = userEvent.setup()
    let ticketBody: Record<string, unknown> | undefined
    const fieldDocument: FormDocument = {
      ...document,
      custom_actions: [],
      fields: [{
        key: 'name', path: 'name', label: 'Название API', type: 'text', required: true,
        visible: true, dynamic: false, placeholder: '', default: '', hint: '',
        file_type: '', width: 1, plural: false, plural_max: null,
        depends_on: null, depends_on_field: null,
      }],
      initial_values: { name: 'Existing' },
    }
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/ticket')) {
        ticketBody = JSON.parse(String(init?.body)) as Record<string, unknown>
        return new Response(JSON.stringify({
          mode: 'ai', draft_id: 'draft-ticket', workflow_id: 'workflow-ticket',
          job_id: 'job-ticket', status: 'running', progress: 'Copilot анализирует…',
        }), { status: 200, headers: { 'content-type': 'application/json' } })
      }
      if (url.includes('/api/v1/ai/drafts/draft-ticket')) {
        return new Response(JSON.stringify({
          id: 'draft-ticket', draft_id: 'draft-ticket', workflow_id: 'workflow-ticket',
          form_id: 'api.create', environment: 'test_int', status: 'complete',
          progress: 'Черновик Copilot готов', error: '',
          result: {
            values: { name: 'From AI' }, baseline: { name: 'Existing' },
            fields: [{ key: 'name', proposed_value: 'From AI', confidence: 'high', source: 'ITSM.summary' }],
            warnings: [], errors: [], valid: true,
          },
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

    await user.click(await screen.findByRole('button', { name: /Подтянуть заявку/ }))
    const dialog = await screen.findByRole('dialog', { name: 'Подтянуть данные из заявки' })
    await user.type(within(dialog).getByRole('textbox', { name: 'Номер заявки' }), 'REQ-42')
    await user.click(within(dialog).getByRole('button', { name: 'Получить данные' }))

    expect(ticketBody).toMatchObject({
      environment: 'test_int',
      ticket_id: 'REQ-42',
      values: { name: 'Existing' },
      form_version: 'version-1',
    })
    expect(await screen.findByDisplayValue('From AI', {}, { timeout: 2500 })).toBeInTheDocument()
    expect(screen.getByText('Проверьте AI-предложения')).toBeInTheDocument()
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

  it('keeps submit progress and failures in the dialog and refreshes confirmation before retry', async () => {
    const user = userEvent.setup()
    let previewCalls = 0
    const submitBodies: Array<Record<string, unknown>> = []
    let finishFirstSubmit: ((response: Response) => void) | undefined
    const firstSubmit = new Promise<Response>((resolve) => { finishFirstSubmit = resolve })
    const confirmedDocument: FormDocument = { ...document, confirm_submit: true, itsm_support: false, custom_actions: [] }

    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/preview')) {
        previewCalls += 1
        return Promise.resolve(new Response(JSON.stringify({
          valid: true,
          values: {},
          errors: [],
          visible_fields: [],
          payload: { operation: 'deploy' },
          confirmation_required: true,
          confirmation_text: 'Отправить изменения?',
          confirmation_token: `confirmation-${previewCalls}`,
        }), { status: 200, headers: { 'content-type': 'application/json' } }))
      }
      if (url.endsWith('/submit')) {
        submitBodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>)
        if (submitBodies.length === 1) return firstSubmit
        return Promise.resolve(new Response(JSON.stringify({
          success: true,
          message: 'Готово',
          submission_id: 'submission-1',
          status: 'success',
          title: 'Создание API',
          content: 'Создано',
          response: {},
          payload: {},
          polling: false,
          poll_interval_ms: null,
        }), { status: 200, headers: { 'content-type': 'application/json' } }))
      }
      return Promise.resolve(new Response(JSON.stringify(confirmedDocument), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }))
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
    const dialog = await screen.findByRole('dialog', { name: 'Подтвердите операцию' })
    await user.click(within(dialog).getByRole('button', { name: 'Подтвердить и отправить' }))

    expect(await within(dialog).findByRole('status')).toHaveTextContent('Отправляю форму')
    expect(within(dialog).getByRole('button', { name: 'Отправляю…' })).toBeDisabled()
    for (const closeButton of within(dialog).getAllByRole('button', { name: 'Закрыть' })) {
      expect(closeButton).toBeDisabled()
    }
    expect(submitBodies[0]).toMatchObject({ confirmation_token: 'confirmation-2' })

    finishFirstSubmit?.(new Response(JSON.stringify({
      detail: { message: 'TFS вернул 401 Unauthorized' },
    }), { status: 422, headers: { 'content-type': 'application/json' } }))

    const submitAlert = await within(dialog).findByRole('alert')
    expect(submitAlert).toHaveTextContent('Не удалось отправить форму')
    expect(submitAlert).toHaveTextContent('TFS вернул 401 Unauthorized')
    expect(within(dialog).getByRole('button', { name: 'Повторить отправку' })).toBeEnabled()

    await user.click(within(dialog).getByRole('button', { name: 'Повторить отправку' }))
    await waitFor(() => expect(submitBodies).toHaveLength(2))
    expect(submitBodies[1]).toMatchObject({ confirmation_token: 'confirmation-3' })
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Подтвердите операцию' })).not.toBeInTheDocument())
  })
})
