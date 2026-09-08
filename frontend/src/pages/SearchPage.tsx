import { FormEvent, KeyboardEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { post } from '../api'
import { EmptyState, ErrorBanner, Modal } from '../components/Feedback'
import { FileJson, LoaderCircle, RefreshCw, Search } from '../components/Icons'
import { ReferenceDetailsModal } from '../components/ReferenceDetailsModal'
import { useEnvironment } from '../environment'

interface SearchResult {
  environment: string
  label?: unknown
  value?: unknown
  item: Record<string, unknown>
}

interface CacheStatus {
  environment: string
  updated_at: number | null
}

type Tier = 'test' | 'regress' | 'prod' | 'all'
type Network = 'int' | 'ext'

const SEARCH_DEBOUNCE_MS = 200
const TIER_OPTIONS: Array<{ value: Tier; label: string }> = [
  { value: 'test', label: 'TEST' },
  { value: 'regress', label: 'REGRESS' },
  { value: 'prod', label: 'PROD' },
  { value: 'all', label: 'ALL' },
]
const NETWORK_OPTIONS: Array<{ value: Network; label: string }> = [
  { value: 'int', label: 'INT' },
  { value: 'ext', label: 'EXT' },
]

function environmentParts(environment: string): { tier: Exclude<Tier, 'all'>; network: Network } {
  const [tier, network] = environment.split('_')
  return {
    tier: tier === 'regress' || tier === 'prod' ? tier : 'test',
    network: network === 'ext' ? 'ext' : 'int',
  }
}

function selectedEnvironments(
  tier: Tier,
  networks: Network[],
  available: Array<{ key: string }>,
): string[] {
  const tiers: Array<Exclude<Tier, 'all'>> = tier === 'all' ? ['test', 'regress', 'prod'] : [tier]
  const allowed = new Set(available.map((item) => item.key))
  const result = tiers.flatMap((item) => NETWORK_OPTIONS
    .filter(({ value }) => networks.includes(value))
    .map(({ value }) => `${item}_${value}`))
  return available.length ? result.filter((key) => allowed.has(key)) : result
}

function resultLabel(result: SearchResult): string {
  return String(result.label || result.item.name || result.item.context_path || result.item.id || 'Без названия')
}

function formatUpdatedAt(value: number | null): string {
  if (!value) return 'Ещё не обновлялось'
  return new Intl.DateTimeFormat('ru-RU', {
    dateStyle: 'medium',
    timeStyle: 'medium',
  }).format(new Date(value * 1000))
}

export function SearchPage() {
  const { environments, environment } = useEnvironment()
  const initial = environmentParts(environment)
  const [kind, setKind] = useState<'api' | 'application'>('api')
  const [tier, setTier] = useState<Tier>(initial.tier)
  const [networks, setNetworks] = useState<Network[]>([initial.network])
  const [query, setQuery] = useState('')
  const [items, setItems] = useState<SearchResult[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [searched, setSearched] = useState(false)
  const [detailResult, setDetailResult] = useState<SearchResult | null>(null)
  const [refreshOpen, setRefreshOpen] = useState(false)
  const [refreshStatus, setRefreshStatus] = useState<CacheStatus[]>([])
  const [refreshStatusLoading, setRefreshStatusLoading] = useState(false)
  const [refreshStatusError, setRefreshStatusError] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  const requestRef = useRef<AbortController | null>(null)
  const debounceRef = useRef<number | undefined>(undefined)
  const scope = useMemo(
    () => selectedEnvironments(tier, networks, environments),
    [environments, networks, tier],
  )

  useEffect(() => {
    const next = environmentParts(environment)
    setTier(next.tier)
    setNetworks([next.network])
  }, [environment])

  const run = useCallback(async (refresh = false) => {
    const normalizedQuery = query.trim()
    if (!normalizedQuery || scope.length === 0) return
    requestRef.current?.abort()
    const controller = new AbortController()
    requestRef.current = controller
    setLoading(true); setError(''); setSearched(true)
    try {
      const result = await post<{ items: SearchResult[] }>('/api/v1/search', {
        kind, environments: scope, query: normalizedQuery, limit: 100, refresh,
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
  }, [kind, query, scope])

  useEffect(() => {
    window.clearTimeout(debounceRef.current)
    requestRef.current?.abort()
    requestRef.current = null
    setLoading(false)
    setItems([])
    setError('')
    setSearched(false)

    if (!query.trim() || scope.length === 0) return

    debounceRef.current = window.setTimeout(() => {
      debounceRef.current = undefined
      void run()
    }, SEARCH_DEBOUNCE_MS)

    return () => window.clearTimeout(debounceRef.current)
  }, [query, kind, scope, run])

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

  const toggleNetwork = (value: Network) => {
    setNetworks((current) => {
      if (current.includes(value)) {
        return current.length === 1 ? current : current.filter((item) => item !== value)
      }
      return NETWORK_OPTIONS.map((item) => item.value).filter((item) => current.includes(item) || item === value)
    })
  }

  const openRefresh = async () => {
    setRefreshOpen(true)
    setRefreshStatus([])
    setRefreshStatusError('')
    setRefreshStatusLoading(true)
    try {
      const response = await post<{ items: CacheStatus[] }>('/api/v1/search/cache-status', {
        kind,
        environments: scope,
      })
      setRefreshStatus(response.items)
    } catch (reason) {
      setRefreshStatusError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setRefreshStatusLoading(false)
    }
  }

  const confirmRefresh = async () => {
    window.clearTimeout(debounceRef.current)
    debounceRef.current = undefined
    setRefreshing(true)
    setRefreshStatusError('')
    try {
      await post('/api/v1/search/refresh', { kind, environments: scope })
      setRefreshOpen(false)
      if (query.trim()) await run()
    } catch (reason) {
      setRefreshStatusError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setRefreshing(false)
    }
  }

  const openResultFromKeyboard = (event: KeyboardEvent<HTMLElement>, result: SearchResult) => {
    if (event.key !== 'Enter' && event.key !== ' ') return
    event.preventDefault()
    setDetailResult(result)
  }

  return (
    <div className="page-stack">
      <div className="page-title"><div><span className="eyebrow">Gravitee Repository</span><h1>Поиск</h1><p>API и приложения по имени, идентификатору и контекстному пути.</p></div></div>
      <section className="search-panel">
        <div className="segmented"><button type="button" className={kind === 'api' ? 'selected' : ''} onClick={() => setKind('api')}>API</button><button type="button" className={kind === 'application' ? 'selected' : ''} onClick={() => setKind('application')}>Приложения</button></div>
        <form className="search-box" onSubmit={submit}><Search /><input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder={kind === 'api' ? 'Название, context path или ID API' : 'Название, AZP или ID приложения'} /><button className="button primary" disabled={loading || !query.trim()}>{loading ? <LoaderCircle className="spin" /> : <Search />} Найти</button></form>
        <div className="search-filters">
          <div className="filter-group"><span>Среда</span><div className="filter-options">{TIER_OPTIONS.map((item) => <button type="button" aria-pressed={tier === item.value} key={item.value} onClick={() => setTier(item.value)} className={tier === item.value ? 'selected' : ''}>{item.label}</button>)}</div></div>
          <div className="filter-group"><span>Контур</span><div className="filter-options">{NETWORK_OPTIONS.map((item) => <button type="button" aria-pressed={networks.includes(item.value)} key={item.value} onClick={() => toggleNetwork(item.value)} className={networks.includes(item.value) ? 'selected' : ''}>{item.label}</button>)}</div></div>
          <button type="button" className="button search-refresh-button" disabled={loading || refreshing || scope.length === 0} onClick={() => void openRefresh()}><RefreshCw size={16} /> Обновить данные</button>
        </div>
      </section>
      {error && <ErrorBanner message={error} />}
      {searched && !loading && items.length === 0 && <EmptyState title="Ничего не найдено" text="Измените запрос или выберите другие окружения." />}
      {items.length > 0 && <section className="search-results"><div className="section-heading"><h2>Результаты</h2><span>{items.length}</span></div>{items.map((result, index) => <article
        className="search-result"
        key={`${result.environment}-${String(result.value ?? result.item.id ?? index)}`}
        role="button"
        tabIndex={0}
        aria-label={`Открыть карточку ${resultLabel(result)}`}
        onClick={() => setDetailResult(result)}
        onContextMenu={(event) => { event.preventDefault(); setDetailResult(result) }}
        onKeyDown={(event) => openResultFromKeyboard(event, result)}
      ><div><div className="search-result-title"><h3>{resultLabel(result)}</h3><span className="environment-chip">{result.environment.replace('_', ' ').toUpperCase()}</span></div><p>{String(result.item.description ?? result.item.context_path ?? result.item.azp ?? '')}</p><code>{String(result.value ?? result.item.id ?? '')}</code><small className="search-result-hint"><FileJson size={13} /> Открыть карточку</small></div></article>)}</section>}
      {detailResult && <ReferenceDetailsModal item={detailResult.item} title={resultLabel(detailResult)} onClose={() => setDetailResult(null)} />}
      {refreshOpen && <Modal
        title="Обновление данных поиска"
        onClose={() => setRefreshOpen(false)}
        footer={<><button type="button" className="button secondary" disabled={refreshing} onClick={() => setRefreshOpen(false)}>Отмена</button><button type="button" className="button primary" disabled={refreshStatusLoading || refreshing} onClick={() => void confirmRefresh()}><RefreshCw size={16} className={refreshing ? 'spin' : ''} /> {refreshing ? 'Обновляю…' : 'Обновить'}</button></>}
      >
        <p className="refresh-confirm-copy">Будет заново загружен справочник для выбранных окружений.</p>
        {refreshStatusLoading && <div className="refresh-status-loading" role="status"><LoaderCircle className="spin" size={18} /> Проверяю даты обновления…</div>}
        {refreshStatusError && <div className="alert error" role="alert">{refreshStatusError}</div>}
        {!refreshStatusLoading && !refreshStatusError && <div className="refresh-status-list">{refreshStatus.map((item) => <div key={item.environment}><strong>{item.environment.replace('_', ' ').toUpperCase()}</strong><span>{formatUpdatedAt(item.updated_at)}</span></div>)}</div>}
      </Modal>}
    </div>
  )
}
