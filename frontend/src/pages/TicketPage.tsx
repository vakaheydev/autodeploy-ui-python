import type { CSSProperties } from 'react'
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { post } from '../api'
import { ErrorBanner, Modal, Spinner } from '../components/Feedback'
import { ArrowLeft, Check, ClipboardList, LoaderCircle, RefreshCw, X, Zap } from '../components/Icons'
import { TicketAttributeValue } from '../components/TicketAttributes'
import { useEnvironment } from '../environment'
import type { TicketActionDocument, TicketActionResponse, TicketCardDocument } from '../types'

export function TicketPage() {
  const { ticketId = '' } = useParams()
  const { environment } = useEnvironment()
  const [card, setCard] = useState<TicketCardDocument | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busyAction, setBusyAction] = useState('')
  const [reload, setReload] = useState(0)
  const [confirmation, setConfirmation] = useState<{ action: TicketActionDocument; text: string; token: string } | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true); setError(''); setNotice(''); setConfirmation(null)
    post<TicketCardDocument>('/api/v1/tickets/card', {
      environment,
      ticket_id: ticketId,
    }, controller.signal).then((next) => {
      if (!controller.signal.aborted) setCard(next)
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) {
        setCard(null)
        setError(reason instanceof Error ? reason.message : String(reason))
      }
    }).finally(() => !controller.signal.aborted && setLoading(false))
    return () => controller.abort()
  }, [environment, reload, ticketId])

  const execute = async (action: TicketActionDocument, token = '') => {
    if (!card) return
    setBusyAction(action.id); setError(''); setNotice('')
    try {
      const response = await post<TicketActionResponse>(`/api/v1/tickets/actions/${encodeURIComponent(action.id)}`, {
        environment,
        ticket_id: card.id,
        card_version: card.version,
        confirmation_token: token,
      })
      if (response.confirmation_required && response.confirmation_token) {
        setConfirmation({
          action,
          text: response.confirmation_text || 'Выполнить действие?',
          token: response.confirmation_token,
        })
        return
      }
      if (!response.success || !response.card) {
        setError(response.message || 'Действие не выполнено')
        return
      }
      setConfirmation(null)
      setCard(response.card)
      setNotice(response.message || 'Действие выполнено')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusyAction('')
    }
  }

  if (loading) return <Spinner label="Загружаю карточку заявки…" />
  if (!card) return <div className="page-stack"><Link className="back-link" to="/tickets"><ArrowLeft size={15} /> Все заявки</Link>{error && <ErrorBanner message={error} />}</div>

  return <div className="ticket-page page-stack">
    <header className="ticket-card-header"><div><Link className="back-link" to="/tickets"><ArrowLeft size={15} /> Все заявки</Link><span className="eyebrow">{card.id}</span><div className="ticket-title-row"><h1><ClipboardList size={31} /> {card.title}</h1>{card.status && <span className={`ticket-badge large ${card.status_tone}`}>{card.status}</span>}</div>{card.subtitle && <p className="ticket-subtitle">{card.subtitle}</p>}{card.description && <p className="ticket-description">{card.description}</p>}</div><div className="ticket-card-meta"><span>{card.environment.replace('_', ' ').toUpperCase()}</span>{card.updated_at && <time>Обновлено: {card.updated_at}</time>}<button type="button" className="button secondary" onClick={() => setReload((current) => current + 1)}><RefreshCw size={15} /> Обновить</button></div></header>
    {error && <ErrorBanner message={error} onClose={() => setError('')} />}
    {notice && <div className="alert success"><Check size={17} /><p>{notice}</p></div>}
    {card.sections.length === 0 && <section className="ticket-section"><p>Корпоративный сервис не вернул дополнительных полей.</p></section>}
    <div className="ticket-sections">{card.sections.map((section) => <section className="ticket-section" key={section.id}><div className="section-heading"><h2>{section.title}</h2></div><dl>{section.attributes.map((attribute) => <div className={`ticket-attribute ${attribute.kind}`} key={attribute.key}><dt>{attribute.label}</dt><dd><TicketAttributeValue attribute={attribute} /></dd></div>)}</dl></section>)}</div>
    {card.actions.length > 0 && <footer className="ticket-actions"><div><strong>Действия с заявкой</strong><span>Выполняются корпоративным Python-сервисом</span></div><div>{card.actions.map((action) => {
      const customStyle = action.color ? ({ '--ticket-action-color': action.color } as CSSProperties) : undefined
      return <button
        type="button"
        className={`button ${action.style} large ${action.color ? 'ticket-action-custom' : ''}`}
        style={customStyle}
        disabled={Boolean(busyAction || action.disabled_reason)}
        title={action.disabled_reason || action.description}
        key={action.id}
        onClick={() => void execute(action)}
      >{busyAction === action.id ? <LoaderCircle className="spin" size={16} /> : <Zap size={16} />}{busyAction === action.id ? 'Выполняю…' : action.label}</button>
    })}</div></footer>}
    {confirmation && <Modal title="Подтвердите действие" closeDisabled={Boolean(busyAction)} onClose={() => setConfirmation(null)} footer={<><button type="button" className="button secondary" disabled={Boolean(busyAction)} onClick={() => setConfirmation(null)}><X size={15} /> Отмена</button><button type="button" className={`button ${confirmation.action.style} ${confirmation.action.color ? 'ticket-action-custom' : ''}`} style={confirmation.action.color ? ({ '--ticket-action-color': confirmation.action.color } as CSSProperties) : undefined} disabled={Boolean(busyAction)} onClick={() => void execute(confirmation.action, confirmation.token)}>{busyAction ? <LoaderCircle className="spin" size={16} /> : <Check size={16} />} Подтвердить</button></>}><p className="ticket-confirmation">{confirmation.text}</p></Modal>}
  </div>
}
