import type { ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

const components = {
  table: ({ children }: { children?: ReactNode }) => <div className="markdown-table-scroll" role="region" aria-label="Таблица в ответе Copilot" tabIndex={0}>
    <table>{children}</table>
  </div>,
  pre: ({ children }: { children?: ReactNode }) => <pre tabIndex={0} aria-label="Блок кода">{children}</pre>,
}

export function MarkdownContent({ children }: { children: string }) {
  return <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>{children}</ReactMarkdown>
}
