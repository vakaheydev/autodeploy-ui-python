import { FormEvent, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { api, post } from '../api'
import { Bot, Check, Code2, LoaderCircle, MessageSquareText, RefreshCw, Send, Sparkles, X } from './Icons'
import { useEnvironment } from '../environment'
import { SearchableSelect } from './SearchableSelect'

interface ModelItem { provider_id: string; model_id: string; provider_name: string; model_name: string; variants: string[] }
interface ChatEvent { sequence: number; kind: string; timestamp: number; payload: Record<string, unknown> }
interface SessionSnapshot { id: string; busy: boolean; provider_id: string; model_id: string; default_variant: string; variants: string[]; opencode_url: string | null; events: ChatEvent[] }

function eventText(event: ChatEvent): string {
  return String(event.payload.text ?? event.payload.message ?? event.payload.title ?? '')
}

export function Copilot() {
  const { environment } = useEnvironment()
  const [session, setSession] = useState<SessionSnapshot | null>(null)
  const [models, setModels] = useState<ModelItem[]>([])
  const [events, setEvents] = useState<ChatEvent[]>([])
  const [message, setMessage] = useState('')
  const [ticketId, setTicketId] = useState('')
  const [ticketVisible, setTicketVisible] = useState(false)
  const [thinking, setThinking] = useState('auto')
  const [modelKey, setModelKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [progress, setProgress] = useState('')
  const transcript = useRef<HTMLDivElement>(null)

  const initialise = async (force = false) => {
    setError('')
    let id = force ? '' : window.localStorage.getItem('autodeploy.ai.session') || ''
    let value: SessionSnapshot
    try {
      if (!id) throw new Error('new')
      value = await api(`/api/v1/ai/sessions/${encodeURIComponent(id)}`)
    } catch {
      value = await post<SessionSnapshot>('/api/v1/ai/sessions', { environment })
      id = value.id
      window.localStorage.setItem('autodeploy.ai.session', id)
    }
    setSession(value)
    setEvents(value.events)
    setBusy(value.busy)
    setModelKey(`${value.provider_id}/${value.model_id}`)
    setThinking('auto')
    const catalog = await api<{ items: ModelItem[] }>('/api/v1/opencode/models')
    setModels(catalog.items)
  }

  useEffect(() => { void initialise().catch((reason: unknown) => setError(reason instanceof Error ? reason.message : String(reason))) }, [])

  useEffect(() => {
    if (!session) return
    const latest = events.reduce((maximum, item) => Math.max(maximum, item.sequence), 0)
    const stream = new EventSource(`/api/v1/ai/sessions/${encodeURIComponent(session.id)}/events?after=${latest}`)
    stream.onmessage = (raw) => {
      const event = JSON.parse(raw.data) as ChatEvent
      setEvents((current) => current.some((item) => item.sequence === event.sequence) ? current : [...current, event])
      if (event.kind === 'progress') { setProgress(eventText(event)); setBusy(true) }
      if (event.kind === 'idle') { setProgress(''); setBusy(false) }
      if (event.kind === 'error') setError(eventText(event))
      window.setTimeout(() => transcript.current?.scrollTo({ top: transcript.current.scrollHeight, behavior: 'smooth' }), 40)
    }
    stream.onerror = () => setProgress((current) => current || 'Переподключаю поток событий…')
    return () => stream.close()
  }, [session?.id])

  useEffect(() => {
    window.setTimeout(() => transcript.current?.scrollTo({ top: transcript.current.scrollHeight, behavior: 'smooth' }), 30)
  }, [events.length, busy, progress])

  const selectedModel = models.find((item) => `${item.provider_id}/${item.model_id}` === modelKey)
  const visibleEvents = useMemo(() => {
    return events.filter((event) => {
      if (['progress', 'idle'].includes(event.kind)) return false
      if (event.kind === 'agent_event') {
        if (event.payload.kind === 'tool') return true
        return ['permission', 'warning', 'error'].includes(String(event.payload.kind))
      }
      return true
    })
  }, [events])

  const sendText = async (text: string, attachedTicket: string | null = null) => {
    if (!session || !text.trim() || busy) return
    const [providerId, ...modelParts] = modelKey.split('/')
    setBusy(true); setError('')
    try {
      await post(`/api/v1/ai/sessions/${encodeURIComponent(session.id)}/messages`, {
        message: text.trim(),
        environment,
        ticket_id: attachedTicket,
        provider_id: providerId,
        model_id: modelParts.join('/'),
        thinking,
      })
    } catch (reason) {
      setBusy(false); setError(reason instanceof Error ? reason.message : String(reason))
      throw reason
    }
  }

  const send = async (event: FormEvent) => {
    event.preventDefault()
    if (!message.trim()) return
    const text = message.trim()
    const attachedTicket = ticketId.trim() || null
    setMessage('')
    try {
      await sendText(text, attachedTicket)
      setTicketId(''); setTicketVisible(false)
    } catch {
      setMessage(text)
    }
  }

  const newChat = async () => {
    if (session) await api(`/api/v1/ai/sessions/${encodeURIComponent(session.id)}`, { method: 'DELETE' }).catch(() => undefined)
    window.localStorage.removeItem('autodeploy.ai.session')
    setEvents([]); setSession(null); setBusy(false)
    await initialise(true)
  }

  return (
    <section className="copilot-card">
      <header className="copilot-header"><div className="copilot-identity"><span className="copilot-logo"><Sparkles /></span><div><span className="eyebrow">OpenCode подключён</span><h2>Gravitee Copilot</h2></div></div><div className="copilot-header-actions">{session?.opencode_url && <a className="button ghost small" href={session.opencode_url} target="_blank" rel="noreferrer"><Code2 size={15} /> OpenCode</a>}<button className="icon-button" onClick={() => void newChat()} title="Новая сессия"><RefreshCw size={16} /></button></div></header>
      <p className="copilot-intro">Опишите задачу или приложите номер заявки. Copilot выберет форму, подготовит план или найдёт объект в Gravitee Repository.</p>
      <div className="chat-transcript" ref={transcript}>
        {visibleEvents.map((event) => <ChatEventView event={event} sessionId={session?.id ?? ''} busy={busy} onCandidate={(formId) => { void sendText(`Выбираю форму ${formId}. Подготовь её заполнение на основе уже собранного контекста.`).catch(() => undefined) }} key={event.sequence} />)}
        {!session && !error && <div className="chat-welcome"><LoaderCircle className="spin" /> Подготавливаю защищённую сессию…</div>}
        {session && busy && <div className="message-row assistant generating-message" aria-live="polite"><div className="message-meta"><span>Copilot</span><span>генерирует ответ</span></div><div className="message-bubble"><span className="generating-orb"><Sparkles size={15} /></span><span className="generating-copy"><strong>{progress || 'Анализирую запрос'}</strong><span className="typing-dots" aria-hidden="true"><i /><i /><i /></span></span><button type="button" onClick={() => post(`/api/v1/ai/sessions/${session.id}/cancel`, {})}>Остановить</button></div></div>}
      </div>
      {error && <div className="chat-error"><X size={16} /><span>{error}</span></div>}
      <form className="chat-composer" onSubmit={(event) => void send(event)}>
        {ticketVisible && <div className="ticket-attachment"><MessageSquareText size={16} /><input value={ticketId} onChange={(event) => setTicketId(event.target.value)} placeholder="Номер заявки, например REQ-12345" autoFocus /><button type="button" className="icon-button" onClick={() => { setTicketVisible(false); setTicketId('') }}><X size={15} /></button></div>}
        <textarea value={message} onChange={(event) => setMessage(event.target.value)} placeholder="Опишите результат, который нужен…" rows={2} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit() } }} />
        <div className="composer-footer"><div className="composer-options"><button type="button" className={`button ghost small ${ticketVisible ? 'selected' : ''}`} onClick={() => setTicketVisible((value) => !value)}><MessageSquareText size={15} /> Заявка</button><SearchableSelect compact clearable={false} ariaLabel="Модель" value={modelKey} onChange={setModelKey} options={models.map((model) => ({ value: `${model.provider_id}/${model.model_id}`, label: model.model_name, description: model.provider_name }))} searchPlaceholder="Найти модель…" /><SearchableSelect compact clearable={false} ariaLabel="Thinking" value={thinking} onChange={setThinking} options={[{ value: 'auto', label: 'Thinking: Auto' }, ...(selectedModel?.variants ?? session?.variants ?? []).map((variant) => ({ value: variant, label: `Thinking: ${variant}` }))]} searchPlaceholder="Найти режим…" /></div><button className="send-button" disabled={!session || busy || !message.trim()} aria-label="Отправить"><Send size={19} /></button></div>
      </form>
    </section>
  )
}

function ChatEventView({ event, sessionId, busy, onCandidate }: { event: ChatEvent; sessionId: string; busy: boolean; onCandidate: (formId: string) => void }) {
  const payload = event.payload
  if (event.kind === 'system') return <div className="system-event"><Bot size={15} /><span>{String(payload.title ?? '')}</span></div>
  if (event.kind === 'agent_event') {
    if (payload.kind === 'permission') return <div className="permission-event"><div><strong>{String(payload.title ?? 'Требуется разрешение')}</strong><small>{String(payload.detail ?? '')}</small></div><div><button className="button secondary small" onClick={() => post(`/api/v1/ai/sessions/${sessionId}/permissions/${payload.permission_id}`, { allow: false })}>Отклонить</button><button className="button primary small" onClick={() => post(`/api/v1/ai/sessions/${sessionId}/permissions/${payload.permission_id}`, { allow: true })}>Разрешить один раз</button></div></div>
    return <div className={`tool-event ${payload.kind}`}><span className="tool-gear">⚙</span><strong>{String(payload.title ?? '')}</strong>{payload.detail ? <code>{String(payload.detail)}</code> : null}</div>
  }
  if (event.kind === 'user') return <div className="message-row user"><div className="message-meta"><span>Вы</span><time>{new Date(event.timestamp * 1000).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}</time><span className="thinking-tag">{String(payload.thinking ?? '—')}</span></div><div className="message-bubble">{String(payload.text ?? '')}</div></div>
  if (event.kind === 'assistant') {
    const candidates = Array.isArray(payload.form_candidates) ? payload.form_candidates as Array<Record<string, unknown>> : []
    const selectedFormId = typeof payload.selected_form_id === 'string' ? payload.selected_form_id : ''
    const handoffToken = typeof payload.handoff_token === 'string' ? payload.handoff_token : ''
    const total = typeof payload.elapsed_seconds === 'number' ? payload.elapsed_seconds : null
    const generation = typeof payload.generation_seconds === 'number' ? payload.generation_seconds : null
    return <div className="message-row assistant"><div className="message-meta"><span>Copilot</span><time>{new Date(event.timestamp * 1000).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}</time><span className="thinking-tag">{String(payload.thinking ?? '—')}</span>{total !== null && <span title={generation !== null ? `Генерация: ${generation.toFixed(1)} с` : 'Общее время'}>{total.toFixed(1)} с{generation !== null ? ` · ген. ${generation.toFixed(1)} с` : ''}</span>}</div><div className="message-bubble markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{String(payload.text ?? '')}</ReactMarkdown>{Boolean(payload.question) && <p className="assistant-question">{String(payload.question)}</p>}{selectedFormId && handoffToken && <Link className="button primary inline-action" to={`/forms/${selectedFormId}`} state={{ handoffToken }}><Sparkles size={16} /> Открыть и заполнить форму</Link>}{!selectedFormId && candidates.length > 0 && <div className="candidate-list">{candidates.map((candidate) => { const formId = String(candidate.form_id); return <button type="button" disabled={busy} onClick={() => onCandidate(formId)} className="candidate" key={formId}><span><strong>{formId}</strong><small>{String(candidate.reason)}</small></span><b>{String(candidate.score)}%</b></button> })}</div>}</div></div>
  }
  if (event.kind === 'error' || event.kind === 'cancelled') return <div className="message-row error"><div className="message-bubble"><X size={16} /> {String(payload.message ?? 'Ошибка AI')}</div></div>
  return null
}
