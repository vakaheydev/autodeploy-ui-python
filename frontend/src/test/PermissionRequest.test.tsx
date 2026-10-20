import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PermissionRequest } from '../components/PermissionRequest'

const payload = {
  permission_id: 'per_1', title: 'Требуется разрешение: example_read', detail: 'example',
  permission_always: true, permission_scope: 'project', permission_resources: ['example/*'],
}
afterEach(() => vi.unstubAllGlobals())

describe('Permission request', () => {
  it.each([
    ['Отклонить', false, false, 'reject', 'Отклонено'],
    ['Разрешить один раз', true, false, 'once', 'Разрешено один раз'],
    ['Разрешать всегда', true, true, 'always', 'Постоянное разрешение сохранено в OpenCode'],
  ] as const)('submits %s and closes the active controls', async (label, allow, always, decision, status) => {
    const fetch = vi.fn().mockResolvedValue(Response.json({ accepted: true, decision }))
    vi.stubGlobal('fetch', fetch)
    render(<PermissionRequest payload={payload} sessionId="chat" active />)
    await userEvent.click(screen.getByRole('button', { name: label }))
    expect(await screen.findByRole('status')).toHaveTextContent(status)
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ allow, always })
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('shows errors and allows retry instead of discarding rejected promises', async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(Response.json({ detail: 'Сервер временно недоступен' }, { status: 503 }))
      .mockResolvedValueOnce(Response.json({ accepted: false, decision: 'expired' }))
    vi.stubGlobal('fetch', fetch)
    render(<PermissionRequest payload={payload} sessionId="chat" active />)
    await userEvent.click(screen.getByRole('button', { name: 'Разрешить один раз' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Сервер временно недоступен')
    await userEvent.click(screen.getByRole('button', { name: 'Разрешить один раз' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Запрос больше не ожидает ответа')
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('prevents duplicate submissions while a reply is pending', async () => {
    let finish!: (value: Response) => void
    const fetch = vi.fn(() => new Promise<Response>(resolve => { finish = resolve }))
    vi.stubGlobal('fetch', fetch)
    render(<PermissionRequest payload={payload} sessionId="chat" active />)
    await userEvent.click(screen.getByRole('button', { name: 'Отклонить' }))
    for (const button of screen.getAllByRole('button')) expect(button).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: 'Отклонить' }))
    expect(fetch).toHaveBeenCalledTimes(1)
    finish(Response.json({ accepted: true, decision: 'reject' }))
    expect(await screen.findByText('Отклонено')).toBeVisible()
  })

  it('closes controls when resolved elsewhere and shows the save scope beforehand', () => {
    const { rerender } = render(<PermissionRequest payload={payload} sessionId="chat" active />)
    expect(screen.getByText(/включая следующие сессии/)).toBeVisible()
    expect(screen.getByText('example/*')).toBeVisible()
    rerender(<PermissionRequest payload={payload} sessionId="chat" active resolution="processed" />)
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Запрос больше не ожидает ответа')
  })

  it('does not offer an actionable always option without a native save rule', () => {
    const { rerender } = render(<PermissionRequest payload={{ ...payload, permission_always: false }} sessionId="chat" active />)
    expect(screen.getByRole('button', { name: 'Разрешать всегда' })).toBeDisabled()
    rerender(<PermissionRequest payload={payload} sessionId="chat" active={false} />)
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })
})
