import { useEffect, useState } from 'react'
import type { ReferenceItem } from '../types'
import { Check, Copy } from './Icons'
import { Modal } from './Feedback'

interface ReferenceDetailsModalProps {
  item: ReferenceItem
  title: string
  onClose: () => void
}

function displayValue(value: unknown): string {
  if (value === null) return 'null'
  if (typeof value === 'object') return JSON.stringify(value, null, 2)
  return String(value)
}

export function ReferenceDetailsModal({ item, title, onClose }: ReferenceDetailsModalProps) {
  const [copiedKey, setCopiedKey] = useState('')

  useEffect(() => setCopiedKey(''), [item])

  const copyField = async (key: string, value: unknown) => {
    const text = displayValue(value)
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard API is unavailable')
      await navigator.clipboard.writeText(text)
    } catch {
      const fallback = document.createElement('textarea')
      fallback.value = text
      fallback.setAttribute('readonly', '')
      fallback.style.position = 'fixed'
      fallback.style.opacity = '0'
      document.body.appendChild(fallback)
      fallback.select()
      document.execCommand('copy')
      fallback.remove()
    }
    setCopiedKey(key)
  }

  return <Modal title={`Карточка: ${title}`} onClose={onClose}>
    <p className="reference-card-hint">Только чтение · нажмите на поле, чтобы скопировать его значение</p>
    <div className="reference-card-fields">
      {Object.entries(item).map(([key, value]) => (
        <button type="button" className={copiedKey === key ? 'copied' : ''} key={key} onClick={() => void copyField(key, value)} title={`Скопировать ${key}`}>
          <span>{key}</span>
          <code>{displayValue(value)}</code>
          {copiedKey === key ? <Check size={16} /> : <Copy size={15} />}
        </button>
      ))}
    </div>
  </Modal>
}
