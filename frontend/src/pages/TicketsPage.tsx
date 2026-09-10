import { FormEvent, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, post } from '../api'
import { EmptyState, ErrorBanner, Spinner } from '../components/Feedback'
import { ChevronLeft, ChevronRight, ClipboardList, LoaderCircle, RefreshCw, Search, X } from '../components/Icons'
import { SearchableSelect } from '../components/SearchableSelect'
import { TicketAttributeValue } from '../components/TicketAttributes'
import { useEnvironment } from '../environment'
import type { TicketFilterDefinition, TicketListConfiguration, TicketListDocument } from '../types'

const QUERY_DELAY_MS = 200

function defaults(configuration: TicketListConfiguration): Record<string, unknown> {
  return Object.fromEntries(configuration.filters.map((filter) => [filter.key, filter.default]))
}

function active(value: unknown): boolean {
  return value !== null && value !== undefined && value !== '' && value !== false
    && (!Array.isArray(value) || value.length > 0)
}

function TicketFilter({ definition, value, onChange }: {
  definition: TicketFilterDefinition
  value: unknown
  onChange: (value: unknown) => void
}) {
  if (definition.kind === 'select') {
    return <label className="ticket-filter"><span>{definition.label}</span><SearchableSelect
      ariaLabel={definition.label}
      compact
      value={String(value ?? '')}
      placeholder={definition.placeholder || 'Все'}
      searchPlaceholder={`Найти: ${definition.label.toLocaleLowerCase('ru')}…`}
      options={definition.options}
      onChange={onChange}
    /></label>
  }
  if (definition.kind === 'multiselect') {
    const selected = Array.isArray(value) ? value.map(String) : []
    const selectedSet = new Set(selected)
    const remaining = definition.options.filter((option) => !selectedSet.has(option.value))
    return <div className="ticket-filter ticket-multifilter"><span>{definition.label}</span><SearchableSelect
      ariaLabel={`Добавить фильтр ${definition.label}`}
      compact
      clearable={false}
      value=""
      placeholder={definition.placeholder || 'Добавить…'}
      options={remaining}
      onChange={(next) => next && onChange([...selected, next])}
    />{selected.length > 0 && <div className="ticket-filter-tags">{selected.map((item) => {
      const option = definition.options.find((candidate) => candidate.value === item)
      return <button type="button" key={item} onClick={() => onChange(selected.filter((candidate) => candidate !== item))}>{option?.label ?? item}<X size={12} /></button>
    })}</div>}</div>
  }
  if (definition.kind === 'boolean') {
    return <label className="ticket-filter ticket-boolean-filter"><span>{definition.label}</span><span className="switch-control"><input type="checkbox" checked={Boolean(value)} onChange={(event) => onChange(event.target.checked)} /><span className="switch" /><span>{value ? 'Да' : 'Нет'}</span></span></label>
  }
  return <label className="ticket-filter"><span>{definition.label}</span><input
    type={definition.kind === 'date' ? 'date' : 'text'}
    value={String(value ?? '')}
    placeholder={definition.placeholder}
    onChange={(event) => onChange(event.target.value)}
  /></label>
}

export function TicketsPage() {
  const { environment } = useEnvironment()
  const [configuration, setConfiguration] = useState<TicketListConfiguration | null>(null)
  const [query, setQuery] = useState('')
  const [filters, setFilters] = useState<Record<string, unknown>>({})
  const [sortKey, setSortKey] = useState('')
  const [direction, setDirection] = useState<'asc' | 'desc'>('desc')
  const [offset, setOffset] = useState(0)
  const [document, setDocument] = useState<TicketListDocument | null>(null)
  const [configurationLoading, setConfigurationLoading] = useState(true)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [reload, setReload] = useState(0)
  const requestRef = useRef<AbortController | null>(null)
  const filterKey = useMemo(() => JSON.stringify(filters), [filters])

  useEffect(() => {
    const controller = new AbortController()
    requestRef.current?.abort()
    setConfiguration(null); setDocument(null); setError(''); setConfigurationLoading(true)
    api<TicketListConfiguration>(`/api/v1/tickets/configuration?environment=${encodeURIComponent(environment)}`, { signal: controller.signal })
      .then((next) => {
        if (controller.signal.aborted) return
        setConfiguration(next)
        setFilters(defaults(next))
        setSortKey(next.default_sort)
        setDirection(next.default_direction)
        setOffset(0)
      })
      .catch((reason: unknown) => !controller.signal.aborted && setError(reason instanceof Error ? reason.message : String(reason)))
      .finally(() => !controller.signal.aborted && setConfigurationLoading(false))
    return () => controller.abort()
  }, [environment])

  useEffect(() => {
    if (!configuration?.enabled) return
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      requestRef.current?.abort()
      requestRef.current = controller
      setLoading(true); setError('')
      post<TicketListDocument>('/api/v1/tickets/query', {
        environment,
        query: query.trim(),
        filters,
        sort_key: sortKey,
        sort_direction: direction,
        offset,
        limit: configuration.page_size,
      }, controller.signal).then((next) => {
        if (!controller.signal.aborted) setDocument(next)
      }).catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : String(reason))
      }).finally(() => {
        if (requestRef.current === controller) {
          requestRef.current = null
          setLoading(false)
        }
      })
    }, QUERY_DELAY_MS)
    return () => { window.clearTimeout(timer); controller.abort() }
  }, [configuration, direction, environment, filterKey, offset, query, reload, sortKey])

  useEffect(() => () => requestRef.current?.abort(), [])

  const changeFilter = (key: string, value: unknown) => {
    setFilters((current) => ({ ...current, [key]: value }))
    setOffset(0)
  }
  const resetFilters = () => {
    if (!configuration) return
    setFilters(defaults(configuration)); setQuery(''); setOffset(0)
  }
  const submit = (event: FormEvent) => {
    event.preventDefault()
    setOffset(0)
    setReload((current) => current + 1)
  }
  const start = document && document.total ? document.offset + 1 : 0
  const end = document ? document.offset + document.items.length : 0
  const hasFilters = query.trim() || Object.values(filters).some(active)

  return <div className="page-stack tickets-page">
    <div className="page-title"><div><span className="eyebrow">Корпоративный ITSM</span><h1>Заявки</h1><p>{configuration?.description || 'Поиск, фильтрация и действия выполняются корпоративным Python-сервисом.'}</p></div></div>
    {configurationLoading && <Spinner label="Загружаю раздел заявок…" />}
    {error && <ErrorBanner message={error} onClose={() => setError('')} />}
    {configuration && !configuration.enabled && <EmptyState title={configuration.empty_title} text={configuration.empty_text} />}
    {configuration?.enabled && <>
      <section className="ticket-toolbar">
        <form className="search-box" onSubmit={submit}><Search size={19} /><input aria-label="Поиск заявок" value={query} onChange={(event) => { setQuery(event.target.value); setOffset(0) }} placeholder="Номер, название или текст заявки…" /><button className="button primary" disabled={loading}>{loading ? <LoaderCircle className="spin" size={16} /> : <Search size={16} />} Найти</button></form>
        {(configuration.filters.length > 0 || configuration.sorts.length > 0) && <div className="ticket-filter-grid">
          {configuration.filters.map((filter) => <TicketFilter key={filter.key} definition={filter} value={filters[filter.key]} onChange={(value) => changeFilter(filter.key, value)} />)}
          {configuration.sorts.length > 0 && <label className="ticket-filter"><span>Сортировка</span><div className="ticket-sort-row"><SearchableSelect ariaLabel="Сортировка заявок" compact clearable={false} value={sortKey} options={configuration.sorts.map((item) => ({ value: item.key, label: item.label }))} onChange={(value) => { setSortKey(value); setOffset(0) }} /><button type="button" className="button secondary" aria-label="Направление сортировки" title={direction === 'desc' ? 'Сначала новые' : 'Сначала старые'} onClick={() => { setDirection((current) => current === 'desc' ? 'asc' : 'desc'); setOffset(0) }}>{direction === 'desc' ? '↓' : '↑'}</button></div></label>}
        </div>}
        <div className="ticket-toolbar-foot"><span>{loading ? 'Обновляю список…' : document ? `Показано ${start}–${end} из ${document.total}` : 'Готово к загрузке'}</span><div>{hasFilters && <button type="button" className="button ghost" onClick={resetFilters}><X size={15} /> Сбросить фильтры</button>}<button type="button" className="button secondary" disabled={loading} onClick={() => setReload((current) => current + 1)}><RefreshCw className={loading ? 'spin' : ''} size={15} /> Обновить</button></div></div>
      </section>
      {!loading && document && document.items.length === 0 && <EmptyState title={configuration.empty_title} text={configuration.empty_text} />}
      {document && document.items.length > 0 && <section className="ticket-list" aria-label="Список заявок">{document.items.map((ticket) => <Link className="ticket-list-card" to={`/tickets/${encodeURIComponent(ticket.id)}`} key={ticket.id}>
        <span className="ticket-list-icon"><ClipboardList size={20} /></span>
        <div className="ticket-list-main"><div className="ticket-list-heading"><div><small>{ticket.id}</small><h2>{ticket.title}</h2></div>{ticket.status && <span className={`ticket-badge ${ticket.status_tone}`}>{ticket.status}</span>}</div>{ticket.subtitle && <p>{ticket.subtitle}</p>}{ticket.attributes.length > 0 && <div className="ticket-list-attributes">{ticket.attributes.map((attribute) => <div key={attribute.key}><small>{attribute.label}</small><TicketAttributeValue attribute={attribute} interactive={false} /></div>)}</div>}</div>
        <div className="ticket-list-side">{ticket.updated_at && <time>{ticket.updated_at}</time>}<ChevronRight size={19} /></div>
      </Link>)}</section>}
      {document && document.total > document.limit && <nav className="ticket-pagination" aria-label="Страницы заявок"><button type="button" className="button secondary" disabled={loading || document.offset === 0} onClick={() => setOffset(Math.max(0, document.offset - document.limit))}><ChevronLeft size={15} /> Назад</button><span>{start}–{end} из {document.total}</span><button type="button" className="button secondary" disabled={loading || !document.has_more} onClick={() => setOffset(document.offset + document.limit)}>Дальше <ChevronRight size={15} /></button></nav>}
    </>}
  </div>
}
