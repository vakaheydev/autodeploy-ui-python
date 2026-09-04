import { useEffect, useState } from 'react'
import { api } from '../api'
import { ErrorBanner } from '../components/Feedback'
import { Activity, LoaderCircle, RefreshCw, ServerCog, Zap } from '../components/Icons'

interface Status { state: string; message: string; version: string; address: string; pid: number | null; agent_loaded: boolean; ownership: string; runtime_dir: string }

export function OpenCodePage() {
  const [status, setStatus] = useState<Status | null>(null)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const load = () => api<Status>('/api/v1/opencode/status').then(setStatus).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : String(reason)))
  useEffect(() => { void load(); const timer = window.setInterval(load, 3000); return () => window.clearInterval(timer) }, [])
  const action = async (name: string) => {
    setBusy(name); setError('')
    try { setStatus(await api<Status>(`/api/v1/opencode/${name}`, { method: 'POST' })) } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) } finally { setBusy('') }
  }
  return <div className="page-stack">
    <div className="page-title"><div><span className="eyebrow">AI backend</span><h1>OpenCode Server</h1><p>Подключение к общему серверу или запуск изолированного localhost-процесса.</p></div></div>
    {error && <ErrorBanner message={error} onClose={() => setError('')} />}
    <section className={`opencode-status ${status?.state === 'ready' ? 'ready' : ''}`}><span className="opencode-status-icon"><Activity /></span><div><span className="eyebrow">Состояние</span><h2>{status?.message ?? 'Проверяю…'}</h2><p>{status?.address || 'Адрес не задан'}{status?.version ? ` · OpenCode ${status.version}` : ''}</p></div><span className={`status-pill ${status?.state}`}>{status?.state ?? 'checking'}</span></section>
    <div className="opencode-actions"><article><ServerCog size={25} /><h2>Подключиться</h2><p>Использовать уже запущенный сервер из `.env`. Сервер останется работать после закрытия приложения.</p><button className="button primary" disabled={Boolean(busy)} onClick={() => void action('connect')}>{busy === 'connect' ? <LoaderCircle className="spin" /> : <Zap />} Подключиться</button></article><article><Zap size={25} /><h2>Создать новый</h2><p>Запустить OpenCode 1.18.18 на свободном порту 127.0.0.1 в безопасной runtime-директории.</p><button className="button secondary" disabled={Boolean(busy)} onClick={() => void action('create')}>{busy === 'create' ? <LoaderCircle className="spin" /> : <ServerCog />} Создать сервер</button></article></div>
    <section className="settings-card"><div><h2>Управление</h2><p>Адреса, таймауты, provider и секреты читаются только Python-сервером из `.env` и не доступны браузеру.</p></div><div className="button-row"><button className="button secondary" disabled={Boolean(busy)} onClick={() => void action('check')}><RefreshCw size={16} /> Проверить</button>{status?.ownership === 'owned' && <button className="button secondary" disabled={Boolean(busy)} onClick={() => void action('restart')}>Перезапустить</button>}<button className="button danger" disabled={Boolean(busy) || status?.state === 'stopped'} onClick={() => void action('stop')}>Отключить</button></div></section>
    {status && <section className="technical-card"><h3>Технические сведения</h3><dl><dt>Ownership</dt><dd>{status.ownership}</dd><dt>PID</dt><dd>{status.pid ?? '—'}</dd><dt>Агенты</dt><dd>{status.agent_loaded ? 'Загружены' : 'Не проверены'}</dd><dt>Runtime</dt><dd><code>{status.runtime_dir || '—'}</code></dd></dl></section>}
  </div>
}
