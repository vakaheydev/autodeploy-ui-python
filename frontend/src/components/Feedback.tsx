import type { ReactNode } from 'react'
import { LoaderCircle, X } from './Icons'

export function Spinner({ label = 'Загрузка…' }: { label?: string }) {
  return <div className="loading-state" role="status"><LoaderCircle className="spin" size={26} /><span>{label}</span></div>
}

export function EmptyState({ title, text, action }: { title: string; text: string; action?: ReactNode }) {
  return <div className="empty-state"><div className="empty-orb" /><h3>{title}</h3><p>{text}</p>{action}</div>
}

export function ErrorBanner({ message, onClose }: { message: string; onClose?: () => void }) {
  return (
    <div className="alert error" role="alert">
      <span>{message}</span>
      {onClose && <button className="icon-button" onClick={onClose} aria-label="Закрыть"><X size={16} /></button>}
    </div>
  )
}
export function Modal({ title, children, onClose, footer, closeDisabled = false, className = '' }: { title: string; children: ReactNode; onClose: () => void; footer?: ReactNode; closeDisabled?: boolean; className?: string }) {
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && !closeDisabled && onClose()}>
      <section className={`modal ${className}`.trim()} role="dialog" aria-modal="true" aria-label={title} aria-busy={closeDisabled || undefined}>
        <header><h2>{title}</h2><button className="icon-button" disabled={closeDisabled} onClick={onClose} aria-label="Закрыть"><X /></button></header>
        <div className="modal-body">{children}</div>
        {footer && <footer>{footer}</footer>}
      </section>
    </div>
  )
}
