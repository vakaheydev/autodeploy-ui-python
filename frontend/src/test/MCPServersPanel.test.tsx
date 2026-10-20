import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MCPServersPanel } from '../components/MCPServersPanel'

afterEach(() => vi.unstubAllGlobals())

describe('MCP servers', () => {
  it('loads actual tools, saves each policy and restarts only that server', async () => {
    const fetch = vi.fn(async (url: string) => Response.json(url.includes('/tools?') ? {
      tools: [{ name: 'read_page', description: 'Read a page', policy: 'ask' }],
    } : { saved: true, applies: 'next_turn', restarted: true }))
    vi.stubGlobal('fetch', fetch)
    const refresh = vi.fn()
    render(<MCPServersPanel servers={[{ name: 'docs', status: 'connected', error: '' }]} onRefresh={refresh} />)
    await userEvent.click(screen.getByText('Инструменты и разрешения'))
    const select = await screen.findByRole('combobox', { name: 'Разрешение docs / read_page' })
    expect(within(select).getAllByRole('option').map(option => option.textContent)).toEqual(['Запретить', 'Всегда спрашивать', 'Разрешить'])
    await userEvent.selectOptions(select, 'allow')
    expect(await screen.findByText(/Сохранено/)).toBeVisible()
    const call = fetch.mock.calls.find(([url]) => url.endsWith('/policy'))!
    expect(JSON.parse((call as unknown as [string, RequestInit])[1].body as string)).toEqual({ policy: 'allow' })
    await userEvent.click(screen.getByRole('button', { name: 'Перезапустить' }))
    expect(await screen.findByText('Перезапуск выполнен')).toBeVisible()
    expect(fetch.mock.calls.some(([url]) => url === '/api/v1/opencode/mcp/docs/restart')).toBe(true)
    expect(refresh).toHaveBeenCalledOnce()
  })

  it('keeps catalog errors visible with a retry action', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({ detail: 'Нет связи с MCP' }, { status: 409 })))
    render(<MCPServersPanel servers={[{ name: 'docs', status: 'failed', error: '' }]} onRefresh={() => {}} />)
    await userEvent.click(screen.getByText('Инструменты и разрешения'))
    expect(await screen.findByRole('alert')).toHaveTextContent('Нет связи с MCP')
    expect(screen.getByRole('button', { name: 'Обновить инструменты' })).toBeEnabled()
  })
})
