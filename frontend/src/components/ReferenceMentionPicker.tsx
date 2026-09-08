import { useEffect, useRef, useState } from 'react'
import { post } from '../api'
import { LoaderCircle, Search, X } from './Icons'

export interface ReferenceMentionItem {
  catalog_id: string
  cache_resource: string
  catalog_label: string
  resource: string
  identifier: string
  label: string
  search_fields: Array<{ key: string; value: string }>
  cached_at: number
}

export interface SelectedReferenceMention extends ReferenceMentionItem {
  marker: string
}

interface SearchResponse {
  items: ReferenceMentionItem[]
  cache_only: boolean
  environment: string
  truncated: boolean
}

export function referenceMentionMarker(item: ReferenceMentionItem): string {
  const label = String(item.label).replace(/\s+/g, ' ').trim()
  const identifier = String(item.identifier).replace(/\s+/g, ' ').trim()
  return `@${label} [ID: ${identifier}]`
}

export function ReferenceMentionPicker({
  open,
  environment,
  onSelect,
  onClose,
}: {
  open: boolean
  environment: string
  onSelect: (item: ReferenceMentionItem) => void
  onClose: () => void
}) {
  const [query, setQuery] = useState('')
  const [items, setItems] = useState<ReferenceMentionItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [truncated, setTruncated] = useState(false)
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!open) return
    setQuery('')
    setItems([])
    setError('')
    setTruncated(false)
    window.setTimeout(() => input.current?.focus(), 0)
  }, [open, environment])

  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    const timer = window.setTimeout(async () => {
      setLoading(true)
      setError('')
      try {
        const result = await post<SearchResponse>('/api/v1/ai/reference-mentions/search', {
          environment,
          query,
          limit: 20,
        }, controller.signal)
        setItems(result.items)
        setTruncated(result.truncated)
      } catch (reason) {
        if (!controller.signal.aborted) {
          setItems([])
          setError(reason instanceof Error ? reason.message : String(reason))
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }, query ? 120 : 0)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [environment, open, query])

  if (!open) return null
  return (
    <div className="mention-picker" role="dialog" aria-label="Выбор объекта справочника" onKeyDown={(event) => {
      if (event.key === 'Escape') { event.preventDefault(); onClose() }
    }}>
      <header>
        <div><span className="mention-symbol">@</span><span><strong>Ссылка на объект</strong><small>Только кэш · {environment.replaceAll('_', ' ').toUpperCase()}</small></span></div>
        <button type="button" className="icon-button" onClick={onClose} aria-label="Закрыть выбор объекта"><X size={15} /></button>
      </header>
      <label className="mention-search">
        <Search size={15} />
        <input ref={input} value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => {
          if (event.key === 'Enter') {
            event.preventDefault()
            if (items[0]) onSelect(items[0])
          }
        }} placeholder="Поиск по полям справочников…" />
        {loading && <LoaderCircle className="spin" size={15} />}
      </label>
      <div className="mention-results" role="listbox" aria-label="Объекты из кэша">
        {!loading && error && <div className="mention-state error">{error}</div>}
        {!loading && !error && items.length === 0 && <div className="mention-state"><strong>В кэше ничего не найдено</strong><span>Откройте нужный справочник или обновите его вручную. Поиск через @ сам данные не загружает.</span></div>}
        {items.map((item) => {
          const details = item.search_fields
            .filter((field) => field.value !== item.label)
            .map((field) => `${field.key}: ${field.value}`)
            .join(' · ')
          return <button type="button" role="option" aria-selected="false" onClick={() => onSelect(item)} key={`${item.catalog_id}:${item.cache_resource}:${item.identifier}`}>
            <span className="mention-result-main"><strong>{item.label}</strong><small>{item.catalog_label}</small>{details && <span>{details}</span>}</span>
            <code>{item.identifier}</code>
          </button>
        })}
      </div>
      {truncated && <footer>Показаны первые 20 совпадений — уточните запрос.</footer>}
    </div>
  )
}
