import { FormEvent, useState } from 'react'
import { post } from '../api'
import { EmptyState, ErrorBanner } from '../components/Feedback'
import { LoaderCircle, RefreshCw, Search } from '../components/Icons'
import { useEnvironment } from '../environment'

interface SearchResult { environment: string; item: Record<string, unknown> }

export function SearchPage() {
  const { environments, environment } = useEnvironment()
  const [kind, setKind] = useState<'api' | 'application'>('api')
  const [scope, setScope] = useState<string[]>([environment])
  const [query, setQuery] = useState('')
  const [items, setItems] = useState<SearchResult[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [searched, setSearched] = useState(false)

  const run = async (event?: FormEvent, refresh = false) => {
    event?.preventDefault()
    if (!query.trim()) return
    setLoading(true); setError(''); setSearched(true)
    try {
      const result = await post<{ items: SearchResult[] }>('/api/v1/search', {
        kind, environments: scope.length ? scope : [environment], query: query.trim(), limit: 100, refresh,
      })
      setItems(result.items)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally { setLoading(false) }
  }

  const toggleScope = (key: string) => setScope((current) => current.includes(key) ? current.filter((item) => item !== key) : [...current, key])
  return (
    <div className="page-stack">
      <div className="page-title"><div><span className="eyebrow">Gravitee Repository</span><h1>Поиск</h1><p>API и приложения по имени, идентификатору и контекстному пути.</p></div></div>
      <section className="search-panel">
        <div className="segmented"><button className={kind === 'api' ? 'selected' : ''} onClick={() => setKind('api')}>API</button><button className={kind === 'application' ? 'selected' : ''} onClick={() => setKind('application')}>Приложения</button></div>
        <form className="search-box" onSubmit={(event) => void run(event)}><Search /><input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder={kind === 'api' ? 'Название, context path или ID API' : 'Название, AZP или ID приложения'} /><button className="button primary" disabled={loading || !query.trim()}>{loading ? <LoaderCircle className="spin" /> : <Search />} Найти</button></form>
        <div className="scope-picker"><span>Окружения:</span>{environments.map((item) => <button key={item.key} onClick={() => toggleScope(item.key)} className={scope.includes(item.key) ? 'selected' : ''}>{item.label}</button>)}<button title="Обновить справочники" className="icon-button" onClick={() => void run(undefined, true)}><RefreshCw size={16} /></button></div>
      </section>
      {error && <ErrorBanner message={error} />}
      {searched && !loading && items.length === 0 && <EmptyState title="Ничего не найдено" text="Измените запрос или выберите другие окружения." />}
      {items.length > 0 && <section className="search-results"><div className="section-heading"><h2>Результаты</h2><span>{items.length}</span></div>{items.map(({ environment: env, item }, index) => <article className="search-result" key={`${env}-${String(item.id ?? index)}`}><div><h3>{String(item.name ?? item.context_path ?? item.id ?? 'Без названия')}</h3><p>{String(item.description ?? item.context_path ?? item.azp ?? '')}</p><code>{String(item.id ?? '')}</code></div><span className="environment-chip">{env.replace('_', ' ').toUpperCase()}</span><details><summary>Все поля</summary><pre>{JSON.stringify(item, null, 2)}</pre></details></article>)}</section>}
    </div>
  )
}
