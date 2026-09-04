import { useEffect } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { Boxes, ChevronDown } from '../components/Icons'
import { EmptyState, ErrorBanner, Spinner } from '../components/Feedback'
import { useAsync } from '../hooks'
import type { Category, Environment } from '../types'
import { useEnvironment } from '../environment'

interface Catalog { categories: Category[]; environments: Environment[] }

export function FormsPage() {
  const { setEnvironments } = useEnvironment()
  const { data, error, loading, reload } = useAsync<Catalog>(
    (signal) => api('/api/v1/catalog', { signal }),
    [],
  )
  useEffect(() => {
    if (data) setEnvironments(data.environments)
  }, [data, setEnvironments])

  return (
    <div className="page-stack">
      <div className="page-title"><div><span className="eyebrow">AutoDeploy</span><h1>Каталог форм</h1><p>Все операции описываются и исполняются Python-сервером.</p></div></div>
      {loading && <Spinner label="Загружаю формы…" />}
      {error && <ErrorBanner message={error} />}
      {data && data.categories.map((category) => (
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
    </div>
  )
}
