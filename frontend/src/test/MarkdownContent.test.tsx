import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { MarkdownContent } from '../components/MarkdownContent'

describe('Copilot Markdown', () => {
  it('renders a semantic table in a keyboard-accessible scroll region', () => {
    render(<MarkdownContent>{`## prod / int

| Название | ID | Файл |
| --- | --- | --- |
| Example | 11111111-2222-4333-8444-555555555555 | \`INT/Apis/FullApis/services/example.FullAPI.json\` |

Примечания:

- Первый пункт
- Второй пункт`}</MarkdownContent>)
    expect(screen.getByRole('heading', { level: 2, name: 'prod / int' })).toBeVisible()
    const region = screen.getByRole('region', { name: 'Таблица в ответе Copilot' })
    expect(region).toHaveAttribute('tabindex', '0')
    expect(within(region).getByRole('table')).toBeVisible()
    expect(within(region).getAllByRole('columnheader')).toHaveLength(3)
    expect(within(region).getByText('11111111-2222-4333-8444-555555555555')).toBeVisible()
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
  })

  it('preserves code whitespace and renders quotes and task lists', () => {
    render(<MarkdownContent>{'> Важное примечание\n\n- [x] Готово\n\n```json\n{\n  "contextPath": "/payments/v2"\n}\n```'}</MarkdownContent>)
    const block = screen.getByLabelText('Блок кода')
    expect(block.textContent).toBe('{\n  "contextPath": "/payments/v2"\n}\n')
    expect(block).toHaveAttribute('tabindex', '0')
    expect(screen.getByRole('checkbox')).toBeChecked()
    expect(screen.getByText('Важное примечание').closest('blockquote')).not.toBeNull()
  })

  it('keeps raw HTML inert and rejects executable link protocols', () => {
    const { container } = render(<MarkdownContent>{'<script>alert(1)</script>\n\n[link](javascript:alert%281%29)'}</MarkdownContent>)
    expect(container.querySelector('script')).toBeNull()
    expect(container.querySelector('a')?.getAttribute('href')).not.toMatch(/^javascript:/i)
  })
})
