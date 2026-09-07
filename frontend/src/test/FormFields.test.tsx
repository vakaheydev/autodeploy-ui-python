import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { FormFields } from '../components/FormFields'
import type { FieldDocument } from '../types'

const base = (overrides: Partial<FieldDocument>): FieldDocument => ({
  key: 'name', path: 'name', label: 'Название', type: 'text', required: true,
  visible: true, dynamic: false, placeholder: '', default: '', hint: '',
  file_type: '', width: 1, plural: false, plural_max: null,
  depends_on: null, depends_on_field: null, ...overrides,
})

describe('FormFields', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('edits fields and approves an inline AI proposal', async () => {
    const user = userEvent.setup()
    const onValuesChange = vi.fn()
    const onReview = vi.fn()
    render(<FormFields
      fields={[base({})]}
      values={{ name: 'Payments' }}
      environment="test_int"
      formId="api.create"
      errors={[]}
      onValuesChange={onValuesChange}
      review={{ name: { proposedValue: 'Payments', confidence: 'high', source: 'ITSM.name' } }}
      onReview={onReview}
    />)
    await user.clear(screen.getByRole('textbox', { name: /Название/ }))
    await user.type(screen.getByRole('textbox', { name: /Название/ }), 'Orders')
    expect(onValuesChange).toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: 'Принять Название' }))
    expect(onReview).toHaveBeenCalledWith('name', true)
  })

  it('renders validation feedback inside the affected field', () => {
    render(<FormFields
      fields={[base({})]}
      values={{ name: '' }}
      environment="test_int"
      formId="api.create"
      errors={[{ field: 'name', code: 'required', message: 'Введите название' }]}
      onValuesChange={() => undefined}
    />)

    const input = screen.getByRole('textbox', { name: /Название/ })
    const field = input.closest('[data-form-field-path="name"]')
    expect(field).toHaveClass('invalid')
    expect(input).toHaveAttribute('aria-invalid', 'true')
    expect(input).toHaveAccessibleDescription('Введите название')
    expect(within(field as HTMLElement).getByRole('alert')).toHaveTextContent('Введите название')
  })

  it('renders a multiselect as explicit multiple choices', async () => {
    const user = userEvent.setup()
    const onValuesChange = vi.fn()
    const field = base({
      key: 'ingresses', path: 'ingresses', label: 'Ингрессы', type: 'multiselect',
      reference: { source: 'local', resource: 'ingress.json', value_key: 'id', label_key: 'name', search_keys: ['name', 'context_path', 'id'], detail_keys: [], required_params: [], endpoint: '/options' },
      options: [{ id: 'internal', name: 'Internal', context_path: '/inside' }, { id: 'external', name: 'External', context_path: '/outside' }],
    })
    render(<FormFields fields={[field]} values={{ ingresses: ['internal'] }} environment="test_int" formId="x" errors={[]} onValuesChange={onValuesChange} />)
    expect(screen.getByPlaceholderText('Можно искать по: name, context_path, id')).toBeVisible()
    expect(screen.getByText('context_path: /inside · id: internal')).toBeVisible()
    expect(screen.getByRole('checkbox', { name: 'Internal' })).toBeChecked()
    await user.click(screen.getByRole('checkbox', { name: 'External' }))
    expect(onValuesChange).toHaveBeenLastCalledWith({ ingresses: ['internal', 'external'] })
  })

  it('keeps selected reference items first and opens a copyable read-only card', async () => {
    const user = userEvent.setup()
    const writeText = vi.spyOn(navigator.clipboard, 'writeText')
    const field = base({
      key: 'ingresses', path: 'ingresses', label: 'Ингрессы', type: 'multiselect',
      reference: { source: 'local', resource: 'ingress.json', value_key: 'id', label_key: 'name', search_keys: ['name'], detail_keys: [], required_params: [], endpoint: '/options' },
      options: [{ id: 'internal', name: 'Internal', description: 'Внутренний' }, { id: 'external', name: 'External', description: 'Внешний' }],
    })

    render(<FormFields fields={[field]} values={{ ingresses: ['external'] }} environment="test_int" formId="x" errors={[]} onValuesChange={() => undefined} />)

    const choices = within(screen.getByRole('group', { name: 'Ингрессы' })).getAllByRole('checkbox')
    expect(choices[0]).toHaveAccessibleName('External')
    await user.type(screen.getByPlaceholderText('Фильтр значений…'), 'Internal')
    const filteredChoices = within(screen.getByRole('group', { name: 'Ингрессы' })).getAllByRole('checkbox')
    expect(filteredChoices[0]).toHaveAccessibleName('External')
    expect(filteredChoices[1]).toHaveAccessibleName('Internal')
    fireEvent.contextMenu(screen.getByText('External'))
    const card = screen.getByRole('dialog', { name: 'Карточка: External' })
    expect(within(card).getByText('Только чтение · нажмите на поле, чтобы скопировать его значение')).toBeVisible()
    await user.click(within(card).getByTitle('Скопировать description'))
    expect(writeText).toHaveBeenCalledWith('Внешний')
  })

  it('does not render a server-hidden conditional field', () => {
    render(<FormFields fields={[base({ key: 'secret', path: 'secret', visible: false })]} values={{ secret: 'x' }} environment="test_int" formId="x" errors={[]} onValuesChange={() => undefined} />)
    expect(screen.queryByText('Название')).not.toBeInTheDocument()
  })

  it('renders a legacy boolean empty marker as blank when a conditional text field appears', () => {
    render(<FormFields
      fields={[base({ dynamic: true, visible: true })]}
      values={{ name: false }}
      environment="test_int"
      formId="x"
      errors={[]}
      onValuesChange={() => undefined}
    />)

    expect(screen.getByRole('textbox', { name: /Название/ })).toHaveValue('')
  })

  it('loads a large reference from the server once and renders the result', async () => {
    const fetch = vi.fn(async () => new Response(JSON.stringify({
      items: [{ id: 'api-103', name: 'service103', context_path: '/api/v1/users/service103' }],
      total: 1,
      has_more: false,
    }), { status: 200, headers: { 'content-type': 'application/json' } }))
    vi.stubGlobal('fetch', fetch)
    const field = base({
      key: 'api', path: 'api', label: 'API', type: 'select',
      reference: { source: 'local', resource: 'apis.json', value_key: 'id', label_key: 'name', search_keys: ['name', 'context_path'], detail_keys: ['context_path'], required_params: [], endpoint: '/api/v1/forms/x/fields/api/options' },
    })

    render(<FormFields fields={[field]} values={{}} environment="test_int" formId="x" errors={[]} onValuesChange={() => undefined} />)

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1))
    await userEvent.click(screen.getByRole('button', { name: 'API' }))
    const option = await screen.findByRole('option', { name: /service103/ })
    expect(screen.getByPlaceholderText('Можно искать по: name, context_path')).toBeVisible()
    expect(within(option).getByText('context_path: /api/v1/users/service103')).toBeVisible()
  })

  it('reloads a server catalog and pins a selection restored from a draft', async () => {
    const selected = { id: 'api-634', name: 'Last API', context_path: '/last' }
    const first = { id: 'api-001', name: 'First API', context_path: '/first' }
    const fetch = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body ?? '{}')) as { values?: Record<string, unknown> }
      const hasDraftSelection = body.values?.api === selected.id
      return new Response(JSON.stringify({
        items: hasDraftSelection ? [selected, first] : [first],
        total: hasDraftSelection ? 2 : 633,
        has_more: !hasDraftSelection,
      }), { status: 200, headers: { 'content-type': 'application/json' } })
    })
    vi.stubGlobal('fetch', fetch)
    const field = base({
      key: 'api', path: 'api', label: 'API', type: 'select',
      reference: { source: 'http', resource: 'apis', value_key: 'id', label_key: 'name', search_keys: ['name', 'context_path'], detail_keys: [], required_params: [], endpoint: '/api/v1/forms/x/fields/api/options' },
    })
    const common = {
      fields: [field], environment: 'test_int', formId: 'x', errors: [],
      onValuesChange: () => undefined,
    }
    const view = render(<FormFields {...common} values={{}} />)

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1))
    // This mirrors FormPage applying a persisted manual/AI draft after the
    // form document (and possibly its first options page) has already loaded.
    view.rerender(<FormFields {...common} values={{ api: selected.id }} />)

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2))
    await userEvent.click(screen.getByRole('button', { name: 'API' }))
    const options = screen.getAllByRole('option')
    expect(options[1]).toHaveTextContent('Last API')
    expect(options[2]).toHaveTextContent('First API')
  })

  it('addresses nested AI review controls by the complete field path', async () => {
    const user = userEvent.setup()
    const onReview = vi.fn()
    const nested = base({ key: 'host', path: 'proxy.host', label: 'Backend host' })
    const block = base({
      key: 'proxy', path: 'proxy', label: 'Proxy', type: 'block',
      fields: [nested],
    })
    render(<FormFields
      fields={[block]}
      values={{ proxy: { host: 'backend.internal' } }}
      environment="test_int"
      formId="x"
      errors={[]}
      onValuesChange={() => undefined}
      review={{ 'proxy.host': { proposedValue: 'backend.internal', confidence: 'medium' } }}
      onReview={onReview}
    />)

    await user.click(screen.getByRole('button', { name: 'Принять Backend host' }))
    expect(onReview).toHaveBeenCalledWith('proxy.host', true)
  })

  it('reuses a free plural slot after an instance was removed', async () => {
    const user = userEvent.setup()
    const onValuesChange = vi.fn()
    render(<FormFields
      fields={[base({ key: 'host', path: 'host', plural: true, plural_max: 4 })]}
      values={{ host: 'one', host_3: 'three' }}
      environment="test_int"
      formId="x"
      errors={[]}
      onValuesChange={onValuesChange}
    />)

    await user.click(screen.getByRole('button', { name: 'Добавить значение' }))
    expect(onValuesChange).toHaveBeenCalledWith({
      host: 'one',
      host_2: '',
      host_3: 'three',
    })
  })

  it('names the add button after a repeatable block', () => {
    const block = base({ key: 'plan', path: 'plan', label: 'План', type: 'block', plural: true, fields: [] })
    render(<FormFields fields={[block]} values={{ plan: {} }} environment="test_int" formId="x" errors={[]} onValuesChange={() => undefined} />)
    expect(screen.getByRole('button', { name: 'Добавить план' })).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Добавить значение' })).not.toBeInTheDocument()
  })
})
