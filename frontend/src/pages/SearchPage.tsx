import { FormEvent, useCallback, useEffect, useRef, useState } from 'react'
import { post } from '../api'
import { EmptyState, ErrorBanner } from '../components/Feedback'
import { LoaderCircle, RefreshCw, Search } from '../components/Icons'
import { useEnvironment } from '../environment'

interface SearchResult {
  environment: string
  label?: unknown
  value?: unknown
  item: Record<string, unknown>
}

const SEARCH_DEBOUNCE_MS = 500

export function SearchPage() {
  const { environments, environment } = useEnvironment()
  const [kind, setKind] = useState<'api' | 'application'>('api')
  const [scope, setScope] = useState<string[]>([environment])
  const [query, setQuery] = useState('')
  const [items, setItems] = useState<SearchResult[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [searched, setSearched] = useState(false)
  const requestRef = useRef<AbortController | null>(null)
  const debounceRef = useRef<number | undefined>(undefined)

  const run = useCallback(async (refresh = false) => {
    const normalizedQuery = query.trim()
    if (!normalizedQuery) return
    requestRef.current?.abort()
    const controller = new AbortController()
    requestRef.current = controller
    setLoading(true); setError(''); setSearched(true)
    try {
      const result = await post<{ items: SearchResult[] }>('/api/v1/search', {
        kind, environments: scope.length ? scope : [environment], query: normalizedQuery, limit: 100, refresh,
      }, controller.signal)
      if (!controller.signal.aborted) setItems(result.items)
    } catch (reason) {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      if (requestRef.current === controller) {
        requestRef.current = null
        setLoading(false)
      }
    }
  }, [environment, kind, query, scope])

  useEffect(() => {
    window.clearTimeout(debounceRef.current)
    requestRef.current?.abort()
    requestRef.current = null
    setLoading(false)
    setItems([])
    setError('')
    setSearched(false)

    if (!query.trim()) {
      return
    }

    debounceRef.current = window.setTimeout(() => {
      debounceRef.current = undefined
      void run()
    }, SEARCH_DEBOUNCE_MS)

    return () => window.clearTimeout(debounceRef.current)
  }, [query, kind, scope, environment, run])

  useEffect(() => () => {
    window.clearTimeout(debounceRef.current)
    requestRef.current?.abort()
  }, [])

  const submit = (event: FormEvent) => {
    event.preventDefault()
    window.clearTimeout(debounceRef.current)
    debounceRef.current = undefined
    void run()
  }

  const refresh = () => {
    window.clearTimeout(debounceRef.current)
    debounceRef.current = undefined
    void run(true)
  }

  const toggleScope = (key: string) => setScope((current) => current.includes(key) ? current.filter((item) => item !== key) : [...current, key])
  return (
    <div className="page-stack">
      <div className="page-title"><div><span className="eyebrow">Gravitee Repository</span><h1>Поиск</h1><p>API и приложения по имени, идентификатору и контекстному пути.</p></div></div>
      <section className="search-panel">
        <div className="segmented"><button className={kind === 'api' ? 'selected' : ''} onClick={() => setKind('api')}>API</button><button className={kind === 'application' ? 'selected' : ''} onClick={() => setKind('application')}>Приложения</button></div>
        <form className="search-box" onSubmit={submit}><Search /><input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder={kind === 'api' ? 'Название, context path или ID API' : 'Название, AZP или ID приложения'} /><button className="button primary" disabled={loading || !query.trim()}>{loading ? <LoaderCircle className="spin" /> : <Search />} Найти</button></form>
        <div className="scope-picker"><span>Окружения:</span>{environments.map((item) => <button key={item.key} onClick={() => toggleScope(item.key)} className={scope.includes(item.key) ? 'selected' : ''}>{item.label}</button>)}<button title="Обновить справочники" className="icon-button" disabled={loading || !query.trim()} onClick={refresh}><RefreshCw size={16} /></button></div>
      </section>
      {error && <ErrorBanner message={error} />}
      {searched && !loading && items.length === 0 && <EmptyState title="Ничего не найдено" text="Измените запрос или выберите другие окружения." />}
      {items.length > 0 && <section className="search-results"><div className="section-heading"><h2>Результаты</h2><span>{items.length}</span></div>{items.map(({ environment: env, label, value, item }, index) => <article className="search-result" key={`${env}-${String(value ?? item.id ?? index)}`}><div><h3>{String(label || item.name || item.context_path || item.id || 'Без названия')}</h3><p>{String(item.description ?? item.context_path ?? item.azp ?? '')}</p><code>{String(value ?? item.id ?? '')}</code></div><span className="environment-chip">{env.replace('_', ' ').toUpperCase()}</span><details><summary>Все поля</summary><pre>{JSON.stringify(item, null, 2)}</pre></details></article>)}</section>}
    </div>
  )
}
