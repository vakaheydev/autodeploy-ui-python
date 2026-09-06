import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { Boxes, ChevronDown, Clock3, FileJson, RefreshCw, Search, Sparkles, Trash2, X } from '../components/Icons'
import { EmptyState, ErrorBanner, Spinner } from '../components/Feedback'
import { useAsync } from '../hooks'
import type { Category, Environment, FormDraftSummary } from '../types'
import { useEnvironment } from '../environment'

interface Catalog { categories: Category[]; environments: Environment[] }
type CatalogTab = 'forms' | 'drafts'

export function FormsPage() {
  const [query, setQuery] = useState('')
  const [tab, setTab] = useState<CatalogTab>('forms')
  const [deleting, setDeleting] = useState('')
  const { setEnvironments } = useEnvironment()
  const forms = useAsync<Catalog>((signal) => api('/api/v1/catalog', { signal }), [])
  const drafts = useAsync<{ items: FormDraftSummary[] }>((signal) => api('/api/v1/drafts', { signal }), [])

  useEffect(() => {
    if (forms.data) setEnvironments(forms.data.environments)
  }, [forms.data, setEnvironments])

  const words = useMemo(
    () => query.trim().toLocaleLowerCase('ru').split(/\s+/).filter(Boolean),
    [query],
  )
  const filtered = useMemo(() => {
    if (!forms.data || !words.length) return forms.data?.categories ?? []
    return forms.data.categories.map((category) => ({
      ...category,
      forms: category.forms.filter((form) => {
        const haystack = [form.id, form.title, form.category_label, ...(form.keywords ?? [])].join(' ').toLocaleLowerCase('ru')
        return words.every((word) => haystack.includes(word))
      }),
    })).filter((category) => category.forms.length)
  }, [forms.data, words])
  const filteredDrafts = useMemo(() => {
    const items = drafts.data?.items ?? []
    if (!words.length) return items
    return items.filter((draft) => {
      const haystack = [draft.form_id, draft.title, draft.environment, draft.source === 'ai' ? 'ии ai copilot' : 'ручной'].join(' ').toLocaleLowerCase('ru')
      return words.every((word) => haystack.includes(word))
    })
  }, [drafts.data, words])
  const found = tab === 'forms'
    ? filtered.reduce((total, category) => total + category.forms.length, 0)
    : filteredDrafts.length

  const removeDraft = async (draftId: string) => {
    setDeleting(draftId)
    try {
      await api(`/api/v1/drafts/${encodeURIComponent(draftId)}`, { method: 'DELETE' })
      drafts.reload()
    } finally {
      setDeleting('')
    }
  }

  return (
    <div className="page-stack">
      <div className="page-title"><div><span className="eyebrow">AutoDeploy</span><h1>Каталог форм</h1><p>Формы и незавершённая работа хранятся на Python-сервере.</p></div>{tab === 'drafts' && <button className="button secondary" onClick={() => drafts.reload()}><RefreshCw size={16} /> Обновить</button>}</div>
      <div className="catalog-tabs" role="tablist" aria-label="Раздел каталога">
        <button role="tab" aria-selected={tab === 'forms'} className={tab === 'forms' ? 'active' : ''} onClick={() => setTab('forms')}><Boxes size={17} /> Формы</button>
        <button role="tab" aria-selected={tab === 'drafts'} className={tab === 'drafts' ? 'active' : ''} onClick={() => setTab('drafts')}><FileJson size={17} /> Черновики <span>{drafts.data?.items?.length ?? 0}</span></button>
      </div>
      <label className="catalog-search"><Search size={20} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={tab === 'forms' ? 'Найти форму по названию, назначению или полю…' : 'Найти черновик по форме, окружению или источнику…'} aria-label={tab === 'forms' ? 'Поиск форм' : 'Поиск черновиков'} />{query && <button type="button" aria-label="Очистить поиск" onClick={() => setQuery('')}><X size={16} /></button>}<span>{query ? `${found} найдено` : tab === 'forms' ? 'Поиск по всем полям' : 'Сохранены до отправки'}</span></label>

      {tab === 'forms' && <>
        {forms.loading && <Spinner label="Загружаю формы…" />}
        {forms.error && <ErrorBanner message={forms.error} />}
        {forms.data && filtered.map((category) => (
          <section className="catalog-section" key={category.id}>
            <div className="section-heading"><div><h2>{category.label}</h2><span>{category.forms.length} форм</span></div></div>
            <div className="form-card-grid">
              {category.forms.map((form) => (
                <Link to={`/forms/${form.id}`} className="form-card" key={form.id}>
                  <span className="form-card-icon"><Boxes size={19} /></span>
                  <div><h3>{form.title}</h3><p>{form.field_count} полей{form.confirm_submit ? ' · требует подтверждения' : ''}</p><code>{form.id}</code></div>
                  <ChevronDown className="rotate-left" size={18} />
                </Link>
              ))}
            </div>
          </section>
        ))}
        {forms.data && query && !found && <EmptyState title="Формы не найдены" text="Попробуйте другое название, действие или ключ поля." />}
      </>}

      {tab === 'drafts' && <>
        {drafts.loading && <Spinner label="Загружаю черновики…" />}
        {drafts.error && <ErrorBanner message={drafts.error} />}
        {drafts.data && filteredDrafts.length === 0 && <EmptyState title={query ? 'Черновики не найдены' : 'Черновиков пока нет'} text={query ? 'Попробуйте другой поисковый запрос.' : 'Начните заполнять любую форму — черновик создастся автоматически.'} />}
        <div className="draft-card-grid">{filteredDrafts.map((draft) => (
          <article className="draft-card" key={draft.id}>
            <Link className="draft-card-main" to={`/forms/${encodeURIComponent(draft.form_id)}?draft=${encodeURIComponent(draft.id)}`}>
              <span className={`draft-card-icon ${draft.source === 'ai' ? 'ai' : ''}`}>{draft.source === 'ai' ? <Sparkles size={19} /> : <FileJson size={19} />}</span>
              <div><span className="draft-kind">{draft.source === 'ai' ? 'Черновик Copilot' : 'Ручной черновик'}</span><h3>{draft.title}</h3><p><Clock3 size={13} /> {new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(draft.updated_at * 1000))} · {draft.environment.replaceAll('_', ' ').toUpperCase()}</p><code>{draft.form_id}</code></div>
              <div className="draft-tags">{draft.review_count > 0 && <span className="tag warning">Проверить {draft.review_count}</span>}{draft.stale && <span className="tag warning">Схема изменилась</span>}</div>
              <ChevronDown className="rotate-left" size={18} />
            </Link>
            <button className="icon-button danger draft-delete" disabled={deleting === draft.id} onClick={() => void removeDraft(draft.id)} aria-label={`Удалить черновик ${draft.title}`}><Trash2 size={16} /></button>
          </article>
        ))}</div>
      </>}
    </div>
  )
}
