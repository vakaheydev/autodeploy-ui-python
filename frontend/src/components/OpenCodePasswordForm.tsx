import { useId, useState, type FormEvent } from 'react'
import { useOpenCode } from '../opencode'
import { ErrorBanner } from './Feedback'
import { KeyRound, LoaderCircle } from './Icons'

export function OpenCodePasswordForm({ autoFocus = false }: { autoFocus?: boolean }) {
  const { status, authenticate, authenticating } = useOpenCode()
  const id = useId()
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!password || busy) return
    setBusy(true)
    setError('')
    try {
      const next = await authenticate(password)
      setPassword('')
      if (next.state !== 'ready') setError(next.message || 'Не удалось подключиться к OpenCode. Попробуйте ещё раз.')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusy(false)
    }
  }
  return <form className="opencode-auth-form" onSubmit={(event) => void submit(event)}>
    <div className="opencode-auth-heading"><span className="opencode-auth-icon"><KeyRound size={22} /></span><div><h3>Сервер требует пароль</h3><p>OpenCode отклонил подключение (401).</p></div></div>
    <code className="opencode-auth-address">{status?.address}</code>
    <label htmlFor={id}>Пароль OpenCode Server</label>
    <input id={id} className="text-control" type="password" autoComplete="current-password" autoFocus={autoFocus} value={password} maxLength={4096} disabled={authenticating} onChange={(event) => setPassword(event.target.value)} />
    <p className="opencode-auth-hint">Пароль сохранится в локальных настройках приложения. Подключение проверится автоматически.</p>
    {error && <ErrorBanner message={error} />}
    <button className="button primary" type="submit" disabled={authenticating || !password}>{authenticating ? <LoaderCircle size={16} className="spin" /> : <KeyRound size={16} />}{authenticating ? 'Проверяю пароль…' : 'Сохранить и подключиться'}</button>
  </form>
}
