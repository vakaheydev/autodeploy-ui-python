import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { Boxes, ChevronDown, Search, X } from '../components/Icons'
import { EmptyState, ErrorBanner, Spinner } from '../components/Feedback'
import { useAsync } from '../hooks'
import type { Category, Environment } from '../types'
import { useEnvironment } from '../environment'

interface Catalog { categories: Category[]; environments: Environment[] }

export function FormsPage() {
  const [query, setQuery] = useState('')
  const { setEnvironments } = useEnvironment()
  const { data, error, loading, reload } = useAsync<Catalog>(
    (signal) => api('/api/v1/catalog', { signal }),
    [],
  )
  useEffect(() => {
    if (data) setEnvironments(data.environments)
  }, [data, setEnvironments])
  const filtered = useMemo(() => {
    const words = query.trim().toLocaleLowerCase('ru').split(/\s+/).filter(Boolean)
    if (!data || !words.length) return data?.categories ?? []
    return data.categories.map((category) => ({
      ...category,
      forms: category.forms.filter((form) => {
        const haystack = [form.id, form.title, form.category_label, ...(form.keywords ?? [])].join(' ').toLocaleLowerCase('ru')
        return words.every((word) => haystack.includes(word))
      }),
    })).filter((category) => category.forms.length)
  }, [data, query])
  const found = filtered.reduce((total, category) => total + category.forms.length, 0)

  return (
    <div className="page-stack">
      <div className="page-title"><div><span className="eyebrow">AutoDeploy</span><h1>Каталог форм</h1><p>Все операции описываются и исполняются Python-сервером.</p></div></div>
      <label className="catalog-search"><Search size={20} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Найти форму по названию, назначению или полю…" aria-label="Поиск форм" />{query && <button type="button" aria-label="Очистить поиск" onClick={() => setQuery('')}><X size={16} /></button>}<span>{query ? `${found} найдено` : 'Поиск по всем полям'}</span></label>
      {loading && <Spinner label="Загружаю формы…" />}
      {error && <ErrorBanner message={error} />}
      {data && filtered.map((category) => (
        <section className="catalog-section" key={category.id}>
          <div className="section-heading"><div><h2>{category.label}</h2><span>{category.forms.length} форм</span></div></div>
          {category.forms.length ? (
            <div className="form-card-grid">
              {category.forms.map((form) => (
                <Link to={`/forms/${form.id}`} className="form-card" key={form.id}>
                  <span className="form-card-icon"><Boxes size={19} /></span>
                  <div><h3>{form.title}</h3><p>{form.field_count} полей{form.confirm_submit ? ' · требует подтверждения' : ''}</p><code>{form.id}</code></div>
                  <ChevronDown className="rotate-left" size={18} />
                </Link>
              ))}
            </div>
          ) : <EmptyState title="Пока пусто" text="В этой категории нет зарегистрированных Python-форм." />}
        </section>
      ))}
      {data && query && !found && <EmptyState title="Формы не найдены" text="Попробуйте другое название, действие или ключ поля." />}
    </div>
  )
}
