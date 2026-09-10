import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { EnvironmentProvider } from '../environment'
import { TicketPage } from '../pages/TicketPage'
import { TicketsPage } from '../pages/TicketsPage'

const configuration = {
  enabled: true,
  description: 'Назначенные пользователю заявки',
  filters: [{
    key: 'status', label: 'Статус', kind: 'select', placeholder: 'Все статусы', default: '',
    options: [{ value: 'active', label: 'Активные' }, { value: 'done', label: 'Завершённые' }],
  }],
  sorts: [{ key: 'updated', label: 'По обновлению' }],
  default_sort: 'updated', default_direction: 'desc', page_size: 20,
  empty_title: 'Заявок пока нет', empty_text: 'Измените фильтры.',
}

const list = {
  items: [{
    id: 'REQ-42', title: 'Создать API Orders', subtitle: 'Новая точка входа',
    status: 'В работе', status_tone: 'info', updated_at: '2026-09-10 10:30',
    attributes: [{ key: 'type', label: 'Тип', value: 'Создание API', kind: 'text', url: '', copyable: false, tone: 'default' }],
  }],
  total: 1, offset: 0, limit: 20, has_more: false,
}

function card(status = 'В работе') {
  return {
    id: 'REQ-42', title: 'Создать API Orders', subtitle: 'Новая точка входа',
    description: 'Описание корпоративной заявки', status, status_tone: 'info',
    updated_at: '2026-09-10 10:30', environment: 'test_int', version: 'version-1',
    sections: [{
      id: 'main', title: 'Основное', attributes: [
        { key: 'author', label: 'Автор', value: 'Иван', kind: 'text', url: '', copyable: true, tone: 'default' },
      ],
    }],
    actions: [{
      id: 'take', label: 'Взять в работу', description: 'Назначить на себя',
      style: 'success', color: '#147D64', confirmation_required: true, disabled_reason: '',
    }],
  }
}

describe('Tickets workspace', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('searches, opens a card and runs a corporate action after confirmation', async () => {
    const requests: Array<{ path: string; body: Record<string, unknown> }> = []
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      const body = init?.body ? JSON.parse(String(init.body)) : {}
      if (path.startsWith('/api/v1/tickets/configuration')) {
        return new Response(JSON.stringify(configuration), { status: 200, headers: { 'content-type': 'application/json' } })
      }
      if (path === '/api/v1/tickets/query') {
        requests.push({ path, body })
        return new Response(JSON.stringify(list), { status: 200, headers: { 'content-type': 'application/json' } })
      }
      if (path === '/api/v1/tickets/card') {
        requests.push({ path, body })
        return new Response(JSON.stringify(card()), { status: 200, headers: { 'content-type': 'application/json' } })
      }
      if (path === '/api/v1/tickets/actions/take') {
        requests.push({ path, body })
        const response = body.confirmation_token
          ? { success: true, message: 'Заявка назначена', card: card('Назначена мне') }
          : { success: false, confirmation_required: true, confirmation_text: 'Взять заявку в работу?', confirmation_token: 'confirm-1' }
        return new Response(JSON.stringify(response), { status: 200, headers: { 'content-type': 'application/json' } })
      }
      throw new Error(`Unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<MemoryRouter initialEntries={['/tickets']}><EnvironmentProvider><Routes>
      <Route path="/tickets" element={<TicketsPage />} />
      <Route path="/tickets/:ticketId" element={<TicketPage />} />
    </Routes></EnvironmentProvider></MemoryRouter>)

    expect(await screen.findByText('Создать API Orders')).toBeVisible()
    await user.type(screen.getByRole('textbox', { name: 'Поиск заявок' }), 'orders')
    await waitFor(() => expect(requests.some(({ path, body }) => path.endsWith('/query') && body.query === 'orders')).toBe(true))
    await user.click(screen.getByRole('link', { name: /Создать API Orders/ }))

    expect(await screen.findByRole('heading', { name: /Создать API Orders/ })).toBeVisible()
    expect(screen.getByText('Иван')).toBeVisible()
    const action = screen.getByRole('button', { name: 'Взять в работу' })
    expect(action.style.getPropertyValue('--ticket-action-color')).toBe('#147D64')
    await user.click(action)
    const dialog = await screen.findByRole('dialog', { name: 'Подтвердите действие' })
    expect(dialog).toHaveTextContent('Взять заявку в работу?')
    await user.click(within(dialog).getByRole('button', { name: 'Подтвердить' }))

    expect(await screen.findByText('Заявка назначена')).toBeVisible()
    expect(screen.getByText('Назначена мне')).toBeVisible()
    const actionRequests = requests.filter(({ path }) => path.endsWith('/actions/take'))
    expect(actionRequests).toHaveLength(2)
    expect(actionRequests[1].body.confirmation_token).toBe('confirm-1')
    expect(actionRequests[1].body.ticket_id).toBe('REQ-42')
  })

  it('shows the corporate disabled state when no provider is connected', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      ...configuration, enabled: false, empty_title: 'Раздел заявок не подключён',
      empty_text: 'Настройте корпоративный TicketProvider.',
    }), { status: 200, headers: { 'content-type': 'application/json' } })))
    render(<MemoryRouter><EnvironmentProvider><TicketsPage /></EnvironmentProvider></MemoryRouter>)

    expect(await screen.findByText('Раздел заявок не подключён')).toBeVisible()
    expect(screen.getByText('Настройте корпоративный TicketProvider.')).toBeVisible()
  })
})
