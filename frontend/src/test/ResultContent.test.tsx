import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ResultContent } from '../components/ResultContent'

describe('operation result copying', () => {
  afterEach(() => vi.restoreAllMocks())

  it('copies URLs from prose and JSON without punctuation, preserving URL parentheses and query', async () => {
    const user = userEvent.setup()
    const write = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue()
    const url = 'https://example.invalid/items/Item_(one)?a=1&b=2#detail'
    const { container } = render(<ResultContent
      message={`Готово (${url}). Ещё: www.example.invalid/help,`}
      content={'{"url": "http://localhost:8765/result", "text": "<script>alert(1)</script>"}\nmailto:help@example.invalid'} />)
    await user.click(screen.getByRole('button', { name: `Скопировать ссылку ${url}` }))
    expect(write).toHaveBeenLastCalledWith(url)
    expect(await screen.findByRole('status')).toHaveTextContent('Ссылка скопирована')
    await user.click(screen.getByRole('button', { name: 'Скопировать ссылку www.example.invalid/help' }))
    expect(write).toHaveBeenLastCalledWith('www.example.invalid/help')
    await user.click(screen.getByRole('button', { name: 'Скопировать ссылку http://localhost:8765/result' }))
    expect(write).toHaveBeenLastCalledWith('http://localhost:8765/result')
    expect(container.querySelector('script')).toBeNull()
    expect(container.querySelector('pre')?.textContent).toContain('<script>alert(1)</script>')
  })

  it('copies a complete block verbatim by mouse or keyboard; a nested URL copies only itself', async () => {
    const user = userEvent.setup()
    const write = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue()
    const text = '  Первая строка\n\tВторая строка\nhttps://example.invalid/task\n'
    const { container, rerender } = render(<ResultContent message="" content="" blocks={[
      { text, label: 'Отчёт', copyable: true },
    ]} />)
    await user.click(container.querySelector('pre')!)
    expect(write).toHaveBeenLastCalledWith(text)
    expect(await screen.findByRole('status')).toHaveTextContent('Блок скопирован')
    screen.getByRole('button', { name: 'Скопировать блок Отчёт' }).focus()
    await user.keyboard('{Enter}')
    expect(write).toHaveBeenCalledTimes(2)
    await user.click(screen.getByRole('button', { name: 'Скопировать ссылку https://example.invalid/task' }))
    expect(write).toHaveBeenCalledTimes(3)
    expect(write).toHaveBeenLastCalledWith('https://example.invalid/task')
    rerender(<ResultContent message="" content="" blocks={[{ text: 'New status', label: '', copyable: false }]} />)
    expect(screen.queryByRole('button', { name: /Скопировать блок/ })).not.toBeInTheDocument()
    expect(container.querySelector('pre')?.textContent).toBe('New status')
  })

  it('reports a failed clipboard write and permits retry without a false success', async () => {
    const user = userEvent.setup()
    const write = vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValueOnce(new Error('denied')).mockResolvedValue()
    render(<ResultContent message="https://example.invalid" content="" />)
    const link = screen.getByRole('button', { name: /Скопировать ссылку/ })
    await user.click(link)
    expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось скопировать')
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    await user.click(link)
    expect(await screen.findByRole('status')).toHaveTextContent('Ссылка скопирована')
    expect(write).toHaveBeenCalledTimes(2)
  })
})
