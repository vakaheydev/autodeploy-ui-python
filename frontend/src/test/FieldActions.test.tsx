import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { EnvironmentProvider } from '../environment'
import { FormPage } from '../pages/FormPage'
import type { FieldDocument, FormDocument } from '../types'

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

const text: FieldDocument = {
  key: 'target', path: 'target', label: 'Текст', type: 'text', required: false,
  visible: true, dynamic: false, placeholder: '', default: '', hint: '', file_type: '', width: 1,
  plural: true, plural_max: null, depends_on: null, depends_on_field: null,
  actions: [
    { id: 'choose', label: 'Выбрать категории', style: 'Secondary', dialog: true, confirmation_required: false },
    { id: 'load', label: 'Загрузить значение', style: 'Secondary', dialog: false, confirmation_required: true },
  ],
}

it('selects reference items from a field dialog and keeps the exact repeated owner through confirmation', async () => {
  const user = userEvent.setup()
  const requests: Array<{ path: string; body: Record<string, unknown> }> = []
  const form: FormDocument = {
    id: 'field-example', title: 'Форма', category: 'other', category_label: 'Прочее',
    version: 'v1', confirm_submit: false, itsm_support: false, http_method: 'POST',
    fields: [text], initial_values: { target: 'Первое', target_2: 'Второе' }, custom_actions: [],
  }
  const dialog = {
    success: true, id: 'choose', owner_field_path: 'target_2', title: 'Категории', description: '',
    form_version: 'v1', values: { choices: [] },
    fields: [{ ...text, key: 'choices', path: 'choices', label: 'Категории', type: 'multiselect',
      plural: false, actions: [], reference: { source: 'local', resource: 'example', value_key: 'id',
        label_key: 'name', search_keys: ['name'], detail_keys: [], required_params: [],
        endpoint: '/api/v1/forms/field-example/actions/choose/dialog/fields/choices/options' },
      options: [{ id: 'a', name: 'Alpha' }, { id: 'b', name: 'Beta' }],
    }],
    actions: [{ id: 'apply', label: 'Применить', style: 'primary', confirmation_required: false,
      requires_valid_dialog: true, close_on_success: true }],
  }
  const json = (body: unknown) => new Response(JSON.stringify(body), { headers: { 'content-type': 'application/json' } })
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    const body = JSON.parse(String(init?.body ?? '{}'))
    if (init?.method === 'POST') requests.push({ path, body })
    if (path.endsWith('/actions/load')) return json(body.confirmation_token
      ? { success: true, status: 'success', values: { target_2: 'Загружено' } }
      : { success: false, confirmation_required: true, confirmation_token: 'confirmed', confirmation_text: 'Обновить поле?' })
    if (path.endsWith('/dialog/actions/apply')) return json({ ...dialog, close_dialog: true,
      form_values: { target_2: 'ALPHA' }, status: 'success', message: 'Выбор применён' })
    if (path.includes('/dialog/fields/')) return json({ items: dialog.fields[0].options, total: 2, has_more: false })
    if (path.includes('/dialog')) return json(dialog)
    return json(form)
  }))
  render(<MemoryRouter initialEntries={['/forms/field-example']}><EnvironmentProvider>
    <Routes><Route path="/forms/:formId" element={<FormPage />} /></Routes>
  </EnvironmentProvider></MemoryRouter>)
  const actions = await screen.findByRole('group', { name: 'Действия поля Текст · 2' })
  expect(actions.closest('[data-form-field-path]')).toHaveAttribute('data-form-field-path', 'target_2')
  await user.click(within(actions).getByRole('button', { name: 'Выбрать категории' }))
  const modal = await screen.findByRole('dialog', { name: 'Категории' })
  await user.click(within(modal).getByRole('checkbox', { name: 'Alpha' }))
  await user.click(within(modal).getByRole('button', { name: 'Применить' }))
  await waitFor(() => expect(screen.getByRole('textbox', { name: 'Текст · 2' })).toHaveValue('ALPHA'))
  expect(screen.getByRole('textbox', { name: 'Текст' })).toHaveValue('Первое')
  const submitted = requests.find(item => item.path.endsWith('/dialog/actions/apply'))!
  expect(submitted.body).toMatchObject({ owner_field_path: 'target_2', dialog_values: { choices: ['a'] } })
  await user.click(within(actions).getByRole('button', { name: 'Загрузить значение' }))
  const confirmation = await screen.findByRole('dialog', { name: 'Подтвердите дополнительное действие' })
  await user.click(within(confirmation).getByRole('button', { name: 'Подтвердить' }))
  await waitFor(() => expect(screen.getByRole('textbox', { name: 'Текст · 2' })).toHaveValue('Загружено'))
  expect(requests.filter(item => item.path.endsWith('/actions/load')).map(item => item.body.owner_field_path)).toEqual(['target_2', 'target_2'])
})
