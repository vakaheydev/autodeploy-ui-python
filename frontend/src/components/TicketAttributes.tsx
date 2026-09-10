import { useState } from 'react'
import { Check, Copy, ExternalLink } from './Icons'
import type { TicketAttribute } from '../types'

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'boolean') return value ? 'Да' : 'Нет'
  if (typeof value === 'object') return JSON.stringify(value, null, 2)
  return String(value)
}

export function TicketAttributeValue({ attribute, interactive = true }: { attribute: TicketAttribute; interactive?: boolean }) {
  const [copied, setCopied] = useState(false)
  const text = displayValue(attribute.value)
  const copy = async () => {
    if (!navigator.clipboard?.writeText) return
    await navigator.clipboard.writeText(text)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1_400)
  }
  let value = attribute.kind === 'json'
    ? <pre>{text}</pre>
    : attribute.kind === 'code'
      ? <code>{text}</code>
      : attribute.kind === 'badge'
        ? <span className={`ticket-badge ${attribute.tone}`}>{text}</span>
        : <span className={attribute.kind === 'multiline' ? 'multiline' : ''}>{text}</span>

  if (attribute.url && interactive) {
    value = <a href={attribute.url} target="_blank" rel="noreferrer">{value}<ExternalLink size={13} /></a>
  }
  return <div className="ticket-attribute-value">
    {value}
    {interactive && attribute.copyable && <button type="button" className="icon-button" aria-label={`Копировать ${attribute.label}`} title="Копировать" onClick={() => void copy()}>{copied ? <Check size={14} /> : <Copy size={14} />}</button>}
  </div>
}
