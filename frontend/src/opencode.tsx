import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { api, post } from './api'
import { OpenCodePasswordForm } from './components/OpenCodePasswordForm'
import { Modal } from './components/Feedback'

export interface OpenCodeStatus {
  state: string
  message: string
  version: string
  address: string
  pid: number | null
  agent_loaded: boolean
  ownership: string
  runtime_dir: string
  auth_required?: boolean
}

interface Connection {
  status: OpenCodeStatus | null
  update: (status: OpenCodeStatus) => void
  refresh: () => Promise<void>
  authenticate: (password: string) => Promise<OpenCodeStatus>
  authenticating: boolean
}

const OpenCodeContext = createContext<Connection | null>(null)

export function useOpenCode() {
  const context = useContext(OpenCodeContext)
  if (!context) throw new Error('OpenCodeProvider is required')
  return context
}

export function OpenCodeProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<OpenCodeStatus | null>(null)
  const [dismissed, setDismissed] = useState<string | null>(null)
  const [authenticating, setAuthenticating] = useState(false)
  const revision = useRef(0)
  const signingIn = useRef(false)
  const update = useCallback((next: OpenCodeStatus) => {
    revision.current += 1
    setStatus(next)
    if (!next.auth_required) setDismissed(null)
  }, [])
  const refresh = useCallback(async () => {
    if (signingIn.current) return
    const current = ++revision.current
    const next = await api<OpenCodeStatus>('/api/v1/opencode/status')
    if (current === revision.current) update(next)
  }, [update])
  useEffect(() => {
    const poll = () => { void refresh().catch(() => undefined) }
    poll()
    const timer = window.setInterval(poll, 3000)
    return () => { window.clearInterval(timer); revision.current += 1 }
  }, [refresh])
  const authenticate = useCallback(async (password: string) => {
    if (signingIn.current) throw new Error('Дождитесь завершения проверки пароля.')
    signingIn.current = true
    setAuthenticating(true)
    revision.current += 1
    try {
      const next = await post<OpenCodeStatus>('/api/v1/opencode/authenticate', { password })
      update(next)
      return next
    } finally {
      signingIn.current = false
      setAuthenticating(false)
    }
  }, [update])
  const modalOpen = Boolean(status?.auth_required && dismissed !== status.address)
  const dismiss = useCallback(() => setDismissed(status?.address ?? ''), [status?.address])
  useEffect(() => {
    if (!modalOpen) return
    const previous = document.activeElement as HTMLElement | null
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') dismiss() }
    window.addEventListener('keydown', escape)
    return () => { window.removeEventListener('keydown', escape); previous?.focus() }
  }, [modalOpen, dismiss])
  return <OpenCodeContext.Provider value={{ status, update, refresh, authenticate, authenticating }}>
    {children}
    {modalOpen && <Modal title="Вход в OpenCode" onClose={dismiss}>
      <OpenCodePasswordForm autoFocus />
      <p className="opencode-auth-hint">Можно закрыть это окно и ввести пароль позже: Настройки → OpenCode.</p>
    </Modal>}
  </OpenCodeContext.Provider>
}
