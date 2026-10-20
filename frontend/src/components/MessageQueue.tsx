import { Clock3, LoaderCircle, Send, X } from './Icons'

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

export function MessageQueue({ items, paused, busy, pending, onRemove, onResume }: {
  items: QueuedMessage[]
  paused: boolean
  busy: boolean
  pending: boolean
  onRemove: (id: string) => void
  onResume: () => void
}) {
  if (!items.length) return null
  return <section className={`message-queue${paused ? ' paused' : ''}`} aria-label="Очередь сообщений">
    <header>
      <span className="queue-icon"><Clock3 size={17} /></span>
      <div><strong>Далее в диалоге <span className="queue-count">{items.length}</span></strong>
        <small role="status">{paused ? 'Очередь на паузе — продолжите, когда будете готовы' : 'OpenCode выполнит сообщения по порядку'}</small></div>
      {paused && <button type="button" className="button secondary small" disabled={busy || pending} onClick={onResume}>
        {pending ? <LoaderCircle size={14} className="spin" /> : <Send size={14} />} Продолжить очередь
      </button>}
    </header>
    <ol>{items.map((item, index) => <li key={item.id}>
      <span className="queue-position" aria-label={`Позиция ${index + 1}`}>{index + 1}</span>
      <div className="queue-message"><p title={item.message}>{item.message}</p>
        <div className="queue-message-meta"><span>{item.environment}</span><span>{item.model_id}</span><span>Thinking: {item.thinking}</span>{item.ticket_id && <span>{item.ticket_id}</span>}</div>
      </div>
      <button type="button" className="icon-button" disabled={pending} onClick={() => onRemove(item.id)} title="Убрать из очереди" aria-label={`Убрать сообщение ${index + 1} из очереди`}><X size={15} /></button>
    </li>)}</ol>
  </section>
}
