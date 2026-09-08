import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { EnvironmentProvider } from '../environment'
import { PluginPage } from '../pages/PluginPage'
import { PluginsPage } from '../pages/PluginsPage'

const textField = {
  key: 'name', path: 'name', label: 'Название', type: 'text', required: true,
  visible: true, dynamic: false, placeholder: '', default: '', hint: '', file_type: '',
  width: 1, plural: false, plural_max: null, depends_on: null, depends_on_field: null,
}

const referenceField = {
  key: 'category', path: 'category', label: 'Категория', type: 'select', required: false,
  visible: true, dynamic: false, placeholder: '', default: null, hint: '', file_type: '',
  width: 1, plural: false, plural_max: null, depends_on: null, depends_on_field: null,
  reference: {
    source: 'corp_http', resource: 'categories', value_key: 'id', label_key: 'name',
    search_keys: ['name', 'code'], detail_keys: ['description'], required_params: [],
    endpoint: '/api/v1/plugins/reports.capacity/fields/category/options',
  },
  options: [{ id: 'internal', name: 'Внутренняя', code: 'INT' }],
}

const pluginDocument = {
  id: 'reports.capacity', title: 'Capacity report', description: 'Отчёт по нагрузке',
  category: 'Отчёты', icon: 'puzzle', version: 'version-1',
  fields: [textField, referenceField], initial_values: { name: 'Gateway', category: 'internal' },
  operations: [{
    id: 'recalculate', label: 'Пересчитать', description: 'Обновить расчёт', style: 'primary',
    confirmation_required: true, requires_valid_fields: true,
  }],
  widgets: [{
    id: 'trend', kind: 'chart', title: 'Нагрузка', chart_type: 'line',
    labels: ['Сейчас', 'После'], series: [{ name: 'RPS', values: [10, 12], color: '' }], y_label: '',
  }],
}

describe('corporate plugin pages', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('searches the catalog and renders shared fields, widgets and confirmed actions', async () => {
    let confirmed = false
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (path === '/api/v1/plugins') return new Response(JSON.stringify({ items: [{
        id: 'reports.capacity', title: 'Capacity report', description: 'Отчёт по нагрузке',
        category: 'Отчёты', icon: 'puzzle', keywords: ['capacity', 'нагрузка'], operation_count: 1,
      }] }), { status: 200, headers: { 'content-type': 'application/json' } })
      if (path.includes('/operations/recalculate')) {
        const body = JSON.parse(String(init?.body))
        if (!body.confirmation_token) return new Response(JSON.stringify({
          success: false, confirmation_required: true,
          confirmation_text: 'Пересчитать корпоративный отчёт?', confirmation_token: 'confirmation-1',
        }), { status: 200, headers: { 'content-type': 'application/json' } })
        confirmed = true
        return new Response(JSON.stringify({
          success: true, message: 'Отчёт пересчитан', values: body.values,
          widgets: [{ id: 'done', kind: 'text', title: 'Готово', text: 'Данные обновлены', tone: 'success' }],
          validation: { valid: true, values: body.values, errors: [], visible_fields: ['name', 'category'] },
        }), { status: 200, headers: { 'content-type': 'application/json' } })
      }
      if (path.endsWith('/state')) {
        const body = JSON.parse(String(init?.body))
        return new Response(JSON.stringify({ ...pluginDocument, initial_values: body.values }), {
          status: 200, headers: { 'content-type': 'application/json' },
        })
      }
      if (path.startsWith('/api/v1/plugins/reports.capacity?')) return new Response(JSON.stringify(pluginDocument), {
        status: 200, headers: { 'content-type': 'application/json' },
      })
      throw new Error(`Unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<MemoryRouter initialEntries={['/plugins']}><EnvironmentProvider><Routes>
      <Route path="/plugins" element={<PluginsPage />} />
      <Route path="/plugins/:pluginId" element={<PluginPage />} />
    </Routes></EnvironmentProvider></MemoryRouter>)

    expect(await screen.findByText('Capacity report')).toBeVisible()
    await user.type(screen.getByRole('textbox', { name: 'Поиск плагинов' }), 'нет совпадений')
    expect(screen.getByText('Плагины не найдены')).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Очистить поиск' }))
    await user.click(screen.getByRole('link', { name: /Capacity report/ }))

    expect(await screen.findByRole('heading', { name: /Capacity report/ })).toBeVisible()
    expect(screen.getByRole('textbox', { name: /Название/ })).toHaveValue('Gateway')
    expect(screen.getByRole('button', { name: 'Категория' })).toHaveTextContent('Внутренняя')
    expect(screen.getByRole('img', { name: 'Нагрузка' })).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Пересчитать' }))
    expect(await screen.findByRole('dialog', { name: 'Подтвердите операцию' })).toHaveTextContent('Пересчитать корпоративный отчёт?')
    await user.click(screen.getByRole('button', { name: 'Выполнить' }))
    expect(await screen.findByText('Отчёт пересчитан')).toBeVisible()
    expect(screen.getByText('Данные обновлены')).toBeVisible()
    await waitFor(() => expect(confirmed).toBe(true))
  })
})
