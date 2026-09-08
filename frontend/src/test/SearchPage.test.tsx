import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { EnvironmentProvider } from '../environment'
import { SearchPage } from '../pages/SearchPage'

function renderPage() {
  return render(
    <MemoryRouter>
      <EnvironmentProvider>
        <SearchPage />
      </EnvironmentProvider>
    </MemoryRouter>,
  )
}

describe('SearchPage', () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('searches automatically after 200 ms of inactivity', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify({ items: [{
      environment: 'test_int',
      label: 'Orders API',
      value: 'api-42',
      item: { title: 'Orders API', context_path: '/orders' },
    }] }), { status: 200, headers: { 'content-type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)
    renderPage()

    fireEvent.change(screen.getByPlaceholderText(/Название, context path/), {
      target: { value: 'ord' },
    })
    await act(async () => vi.advanceTimersByTimeAsync(100))
    fireEvent.change(screen.getByPlaceholderText(/Название, context path/), {
      target: { value: 'orders' },
    })
    await act(async () => vi.advanceTimersByTimeAsync(199))
    expect(fetchMock).not.toHaveBeenCalled()

    await act(async () => vi.advanceTimersByTimeAsync(1))
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toMatchObject({
      kind: 'api',
      query: 'orders',
      environments: ['test_int'],
    })
    expect(screen.getByText('Orders API')).toBeVisible()
    expect(screen.getByText('api-42')).toBeVisible()
    const title = screen.getByRole('heading', { name: 'Orders API' }).closest('.search-result-title')
    expect(title).not.toBeNull()
    expect(within(title as HTMLElement).getByText('TEST INT')).toBeVisible()
  })

  it('searches immediately on Enter without repeating the debounced request', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(
      JSON.stringify({ items: [] }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    ))
    vi.stubGlobal('fetch', fetchMock)
    renderPage()

    const input = screen.getByPlaceholderText(/Название, context path/)
    fireEvent.change(input, { target: { value: '/orders' } })
    fireEvent.submit(input.closest('form')!)

    expect(fetchMock).toHaveBeenCalledTimes(1)
    await act(async () => vi.advanceTimersByTimeAsync(200))
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('combines an ALL tier with the selected INT or EXT contours', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(
      JSON.stringify({ items: [] }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    ))
    vi.stubGlobal('fetch', fetchMock)
    renderPage()

    fireEvent.click(screen.getByRole('button', { name: 'ALL' }))
    fireEvent.click(screen.getByRole('button', { name: 'EXT' }))
    fireEvent.click(screen.getByRole('button', { name: 'INT' }))
    fireEvent.change(screen.getByPlaceholderText(/Название, context path/), {
      target: { value: 'orders' },
    })
    await act(async () => vi.advanceTimersByTimeAsync(200))

    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body)).environments).toEqual([
      'test_ext', 'regress_ext', 'prod_ext',
    ])
  })

  it('shows cache dates before refreshing the selected environments', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (path.endsWith('/api/v1/search/cache-status')) {
        return new Response(JSON.stringify({
          items: [{ environment: 'test_int', updated_at: 1_700_000_000 }],
        }), { status: 200, headers: { 'content-type': 'application/json' } })
      }
      if (path.endsWith('/api/v1/search/refresh')) {
        return new Response(JSON.stringify({
          items: [{ environment: 'test_int', updated_at: 1_700_000_100, count: 1 }],
        }), { status: 200, headers: { 'content-type': 'application/json' } })
      }
      return new Response(JSON.stringify({ items: [{
        environment: 'test_int',
        label: 'Orders API',
        value: 'api-42',
        item: { id: 'api-42', name: 'Orders API', context_path: '/orders' },
      }] }), { status: 200, headers: { 'content-type': 'application/json' } })
    })
    vi.stubGlobal('fetch', fetchMock)
    renderPage()
    const input = screen.getByPlaceholderText(/Название, context path/)
    fireEvent.change(input, { target: { value: 'orders' } })
    fireEvent.submit(input.closest('form')!)
    await screen.findByText('Orders API')

    fireEvent.click(screen.getByRole('button', { name: /Обновить данные/ }))
    const dialog = await screen.findByRole('dialog', { name: 'Обновление данных поиска' })
    expect(await within(dialog).findByText('TEST INT')).toBeVisible()
    expect(within(dialog).getByText(/2023/)).toBeVisible()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Обновить' }))

    await waitFor(() => expect(fetchMock.mock.calls.some(([input, init]) => {
      if (!String(input).endsWith('/api/v1/search/refresh') || !init?.body) return false
      return JSON.parse(String(init.body)).environments[0] === 'test_int'
    })).toBe(true))
  })

  it('opens a search result in the shared read-only reference card', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ items: [{
      environment: 'test_int',
      label: 'Orders API',
      value: 'api-42',
      item: { id: 'api-42', name: 'Orders API', context_path: '/orders' },
    }] }), { status: 200, headers: { 'content-type': 'application/json' } })))
    renderPage()
    const input = screen.getByPlaceholderText(/Название, context path/)
    fireEvent.change(input, { target: { value: 'orders' } })
    fireEvent.submit(input.closest('form')!)

    fireEvent.click(await screen.findByRole('button', { name: 'Открыть карточку Orders API' }))
    const dialog = screen.getByRole('dialog', { name: 'Карточка: Orders API' })
    expect(within(dialog).getByText('/orders')).toBeVisible()
    expect(within(dialog).getByTitle('Скопировать context_path')).toBeVisible()
  })
})
