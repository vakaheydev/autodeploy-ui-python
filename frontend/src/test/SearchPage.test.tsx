import { act, fireEvent, render, screen } from '@testing-library/react'
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

  it('searches automatically after 500 ms of inactivity', async () => {
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
    await act(async () => vi.advanceTimersByTimeAsync(300))
    fireEvent.change(screen.getByPlaceholderText(/Название, context path/), {
      target: { value: 'orders' },
    })
    await act(async () => vi.advanceTimersByTimeAsync(499))
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
    await act(async () => vi.advanceTimersByTimeAsync(500))
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
