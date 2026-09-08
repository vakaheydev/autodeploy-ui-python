import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { ChevronDown, Puzzle, Search, X } from '../components/Icons'
import { EmptyState, ErrorBanner, Spinner } from '../components/Feedback'
import { useAsync } from '../hooks'
import type { PluginSummary } from '../types'

export function PluginsPage() {
  const [query, setQuery] = useState('')
  const catalog = useAsync<{ items: PluginSummary[] }>(
    (signal) => api('/api/v1/plugins', { signal }),
    [],
  )
  const words = useMemo(
    () => query.trim().toLocaleLowerCase('ru').split(/\s+/).filter(Boolean),
    [query],
  )
  const filtered = useMemo(() => (catalog.data?.items ?? []).filter((plugin) => {
    const haystack = [plugin.id, plugin.title, plugin.description, plugin.category, ...plugin.keywords]
      .join(' ')
      .toLocaleLowerCase('ru')
    return words.every((word) => haystack.includes(word))
  }), [catalog.data, words])
  const categories = useMemo(() => {
    const result = new Map<string, PluginSummary[]>()
    filtered.forEach((plugin) => result.set(
      plugin.category || 'Корпоративные',
      [...(result.get(plugin.category || 'Корпоративные') ?? []), plugin],
    ))
    return [...result]
  }, [filtered])

  return <div className="page-stack plugins-page">
    <div className="page-title"><div><span className="eyebrow">Расширения Python</span><h1>Плагины</h1><p>Корпоративные рабочие страницы, зарегистрированные в серверном ядре.</p></div></div>
    <label className="catalog-search"><Search size={20} /><input aria-label="Поиск плагинов" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Найти плагин по названию или назначению…" />{query && <button type="button" aria-label="Очистить поиск" onClick={() => setQuery('')}><X size={16} /></button>}<span>{query ? `${filtered.length} найдено` : 'По всему каталогу'}</span></label>
    {catalog.loading && <Spinner label="Загружаю плагины…" />}
    {catalog.error && <ErrorBanner message={catalog.error} />}
    {catalog.data && catalog.data.items.length === 0 && <EmptyState title="Плагины пока не подключены" text="Укажите корпоративный регистратор плагинов в настройках расширений." />}
    {catalog.data && catalog.data.items.length > 0 && filtered.length === 0 && <EmptyState title="Плагины не найдены" text="Попробуйте другое название или ключевое слово." />}
    {categories.map(([category, plugins]) => <section className="catalog-section" key={category}>
      <div className="section-heading"><div><h2>{category}</h2><span>{plugins.length} плагинов</span></div></div>
      <div className="plugin-card-grid">{plugins.map((plugin) => <Link to={`/plugins/${encodeURIComponent(plugin.id)}`} className="plugin-card" key={plugin.id}>
        <span className="plugin-card-icon"><Puzzle size={20} /></span>
        <div><h3>{plugin.title}</h3>{plugin.description && <p>{plugin.description}</p>}<small>{plugin.operation_count ? `${plugin.operation_count} операций` : 'Информационная страница'}</small></div>
        <ChevronDown className="rotate-left" size={18} />
      </Link>)}</div>
    </section>)}
  </div>
}
