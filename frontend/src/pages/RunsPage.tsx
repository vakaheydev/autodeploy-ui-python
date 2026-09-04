import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { EmptyState, ErrorBanner, Spinner } from '../components/Feedback'
import { History, RefreshCw, Trash2 } from '../components/Icons'
import { useAsync } from '../hooks'
import type { RunRecord } from '../types'

export function RunsPage() {
  const { data, error, loading, reload } = useAsync<{ items: RunRecord[] }>((signal) => api('/api/v1/runs', { signal }), [])
  const [deleting, setDeleting] = useState('')
  const remove = async (id: string) => {
    setDeleting(id)
    try { await api(`/api/v1/runs/${encodeURIComponent(id)}`, { method: 'DELETE' }); reload() } finally { setDeleting('') }
  }
  return <div className="page-stack">
    <div className="page-title"><div><span className="eyebrow">Аудит операций</span><h1>История запусков</h1><p>Последние успешно отправленные формы хранятся локально.</p></div><button className="button secondary" onClick={() => reload()}><RefreshCw size={16} /> Обновить</button></div>
    {loading && <Spinner />}{error && <ErrorBanner message={error} />}
    {data?.items.length === 0 && <EmptyState title="История пуста" text="После первой успешной отправки запись появится здесь." />}
    <div className="runs-list">{data?.items.map((run) => <article className="run-row" key={run.run_id}><span className="run-icon"><History size={18} /></span><div className="run-main"><h3>{run.form_id}</h3><p>{new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(run.timestamp * 1000))} · {run.environment.replace('_', ' ').toUpperCase()}</p></div>{run.stale ? <span className="tag warning">Форма изменилась</span> : <Link className="button secondary small" to={`/forms/${run.form_id}`} state={{ values: run.form_data }}>Повторить</Link>}<button className="icon-button danger" disabled={deleting === run.run_id} onClick={() => void remove(run.run_id)} aria-label="Удалить"><Trash2 size={16} /></button></article>)}</div>
  </div>
}
