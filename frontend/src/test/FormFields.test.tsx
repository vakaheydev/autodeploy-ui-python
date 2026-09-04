import { render, screen, waitFor } from '@testing-library/react'
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
      review={{ name: { status: 'pending', confidence: 'high', source: 'ITSM.name' } }}
      onReview={onReview}
    />)
    await user.clear(screen.getByRole('textbox', { name: /Название/ }))
    await user.type(screen.getByRole('textbox', { name: /Название/ }), 'Orders')
    expect(onValuesChange).toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: 'Принять Название' }))
    expect(onReview).toHaveBeenCalledWith('name', true)
  })

  it('renders a multiselect as explicit multiple choices', async () => {
    const user = userEvent.setup()
    const onValuesChange = vi.fn()
    const field = base({
      key: 'ingresses', path: 'ingresses', label: 'Ингрессы', type: 'multiselect',
      reference: { source: 'local', resource: 'ingress.json', value_key: 'id', label_key: 'name', search_keys: ['name'], detail_keys: [], required_params: [], endpoint: '/options' },
      options: [{ id: 'internal', name: 'Internal' }, { id: 'external', name: 'External' }],
    })
    render(<FormFields fields={[field]} values={{ ingresses: ['internal'] }} environment="test_int" formId="x" errors={[]} onValuesChange={onValuesChange} />)
    expect(screen.getByRole('checkbox', { name: 'Internal' })).toBeChecked()
    await user.click(screen.getByRole('checkbox', { name: 'External' }))
    expect(onValuesChange).toHaveBeenLastCalledWith({ ingresses: ['internal', 'external'] })
  })

  it('does not render a server-hidden conditional field', () => {
    render(<FormFields fields={[base({ key: 'secret', path: 'secret', visible: false })]} values={{ secret: 'x' }} environment="test_int" formId="x" errors={[]} onValuesChange={() => undefined} />)
    expect(screen.queryByText('Название')).not.toBeInTheDocument()
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
    expect(await screen.findByRole('option', { name: 'service103' })).toBeInTheDocument()
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
      review={{ 'proxy.host': { status: 'pending', confidence: 'medium' } }}
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
})
