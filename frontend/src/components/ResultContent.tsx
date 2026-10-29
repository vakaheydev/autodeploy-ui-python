import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Check, Copy, X } from './Icons'
import type { ResultTextBlock } from '../types'

// Keep result text (including JSON/indentation) intact; only decorate URLs.
// Quotes and angle brackets delimit URLs; balanced parentheses remain part of them.
function linkText(text: string, copy: (value: string, message: string) => void): ReactNode[] {
  const nodes: ReactNode[] = []
  const pattern = /\b(?:https?:\/\/|ftp:\/\/|mailto:|www\.)[^\s<>"'`]+/gi
  let offset = 0
  for (const match of text.matchAll(pattern)) {
    const start = match.index!
    let url = match[0].replace(/[.,;:!?]+$/, '')
    // Exclude surrounding prose/Markdown punctuation, but preserve URL syntax.
    while (/[)\]}]$/.test(url)) {
      const closing = url.at(-1)!
      const opening = { ')': '(', ']': '[', '}': '{' }[closing]!
      if (url.split(closing).length <= url.split(opening).length) break
      url = url.slice(0, -1).replace(/[.,;:!?]+$/, '')
    }
    nodes.push(text.slice(offset, start))
    nodes.push(<button key={start} type="button" className="result-link"
      title="Скопировать ссылку" aria-label={`Скопировать ссылку ${url}`}
      onClick={(event) => { event.stopPropagation(); copy(url, 'Ссылка скопирована') }}>
      {url}
    </button>)
    offset = start + url.length
  }
  nodes.push(text.slice(offset))
  return nodes
}

export function ResultContent({ message, content, blocks = [] }: {
  message: string
  content: string
  blocks?: ResultTextBlock[]
}) {
  const [notice, setNotice] = useState<{ text: string; error: boolean } | null>(null)
  const timer = useRef<number | undefined>(undefined)
  const attempt = useRef(0)
  useEffect(() => () => { window.clearTimeout(timer.current); attempt.current += 1 }, [])

  const copy = async (text: string, success: string) => {
    const current = ++attempt.current
    window.clearTimeout(timer.current)
    setNotice(null)
    let next: { text: string; error: boolean }
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable')
      await navigator.clipboard.writeText(text)
      next = { text: success, error: false }
    } catch {
      next = { text: 'Не удалось скопировать. Разрешите доступ к буферу обмена и повторите.', error: true }
    }
    if (current !== attempt.current) return
    setNotice(next)
    timer.current = window.setTimeout(() => setNotice(null), next.error ? 6000 : 3000)
  }

  return <>
    {message && <p className="result-message">{linkText(message, copy)}</p>}
    {content && <pre className="result-text">{linkText(content, copy)}</pre>}
    {blocks.map((block, index) => <div key={index}
      className={`result-text-block ${block.copyable ? 'copyable' : ''}`}
      onClick={block.copyable ? () => void copy(block.text, 'Блок скопирован') : undefined}>
      {block.copyable ? <button type="button" className="result-block-copy"
        aria-label={`Скопировать блок ${block.label || index + 1}`}
        onClick={(event) => { event.stopPropagation(); void copy(block.text, 'Блок скопирован') }}>
        <span>{block.label || 'Текст для копирования'}</span><span><Copy size={16} /> Копировать целиком</span>
      </button> : block.label && <div className="result-block-label">{block.label}</div>}
      <pre className="result-text">{linkText(block.text, copy)}</pre>
    </div>)}
    {notice && <div className={`result-copy-notice ${notice.error ? 'error' : ''}`} role={notice.error ? 'alert' : 'status'} aria-atomic="true">
      {notice.error ? <X size={18} /> : <Check size={18} />}<span>{notice.text}</span>
      <button type="button" className="icon-button" aria-label="Закрыть уведомление" onClick={() => setNotice(null)}><X size={16} /></button>
    </div>}
  </>
}
