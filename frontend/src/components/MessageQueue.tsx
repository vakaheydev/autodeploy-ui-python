import { ArrowDown, ArrowUp, Clock3, LoaderCircle, Send, X, Zap } from './Icons'

export interface QueuedMessage {
  id: string
  message: string
  environment: string
  ticket_id: string | null
  model_id: string
  thinking: string
}

export interface MessageQueueState {
  queue_supported?: boolean
  queue_enabled?: boolean
  queue_ready?: boolean
  queue_paused?: boolean
  queue_limit?: number
  queue?: QueuedMessage[]
  active_environment?: string
}

export function MessageQueue({ items, paused, busy, pending, onRemove, onResume, onSend, onMove }: {
  items: QueuedMessage[]
  paused: boolean
  busy: boolean
  pending: boolean
  onRemove: (id: string) => void
  onResume: () => void
  onSend: (id: string) => void
  onMove: (id: string, direction: 'up' | 'down') => void
}) {
  if (!items.length) return null
  return <section className={`message-queue${paused ? ' paused' : ''}`} aria-label="Очередь сообщений">
    <header>
      <span className="queue-icon"><Clock3 size={17} /></span>
      <div><strong>Очередь сообщений <span className="queue-count">{items.length}</span></strong></div>
      {paused && <button type="button" className="icon-button" disabled={busy || pending} onClick={onResume} title="Продолжить очередь" aria-label="Продолжить очередь">
        {pending ? <LoaderCircle size={16} className="spin" /> : <Send size={16} />}
      </button>}
    </header>
    <ol>{items.map((item, index) => <li key={item.id}>
      <span className="queue-position" aria-label={`Позиция ${index + 1}`}>{index + 1}</span>
      <div className="queue-message"><p title={item.message}>{item.message}</p>
      </div>
      <div className="queue-item-actions">
        <button type="button" className="icon-button queue-send-now" disabled={pending} onClick={() => onSend(item.id)} title="Отправить сейчас — на ближайшем шаге OpenCode" aria-label={`Отправить сообщение ${index + 1} сейчас`}><Zap size={16} /></button>
        <button type="button" className="icon-button" disabled={pending || index === 0} onClick={() => onMove(item.id, 'up')} title="Выше" aria-label={`Переместить сообщение ${index + 1} выше`}><ArrowUp size={15} /></button>
        <button type="button" className="icon-button" disabled={pending || index === items.length - 1} onClick={() => onMove(item.id, 'down')} title="Ниже" aria-label={`Переместить сообщение ${index + 1} ниже`}><ArrowDown size={15} /></button>
        <button type="button" className="icon-button" disabled={pending} onClick={() => onRemove(item.id)} title="Убрать из очереди" aria-label={`Убрать сообщение ${index + 1} из очереди`}><X size={15} /></button>
      </div>
    </li>)}</ol>
  </section>
}
