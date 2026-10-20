import { useState } from 'react'
import { post } from '../api'

export function PermissionRequest({ payload, sessionId, active, resolution }: {
  payload: Record<string, unknown>
  sessionId: string
  active: boolean
  resolution?: string
}) {
  const [pending, setPending] = useState(false)
  const [decision, setDecision] = useState('')
  const [error, setError] = useState('')
  const resolved = decision || resolution || (!active ? 'expired' : '')
  const canSave = payload.permission_always === true
  const resources = Array.isArray(payload.permission_resources) ? payload.permission_resources.map(String) : []
  const scope = payload.permission_scope === 'project'
    ? 'В проекте OpenCode, включая следующие сессии'
    : 'В текущей сессии OpenCode'

  async function reply(allow: boolean, always = false) {
    if (pending || resolved) return
    setPending(true)
    setError('')
    try {
      const result = await post<{ accepted: boolean; decision: string }>(
        `/api/v1/ai/sessions/${encodeURIComponent(sessionId)}/permissions/${encodeURIComponent(String(payload.permission_id))}`,
        { allow, always },
      )
      setDecision(result.decision || (result.accepted ? (always ? 'always' : allow ? 'once' : 'reject') : 'expired'))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setPending(false)
    }
  }

  const status = resolved === 'always' ? 'Постоянное разрешение сохранено в OpenCode'
    : resolved === 'once' ? 'Разрешено один раз'
    : resolved === 'reject' ? 'Отклонено'
    : 'Запрос больше не ожидает ответа'

  return <section className={`permission-event permission-request${resolved ? ' resolved' : ''}`} aria-label="Разрешение инструмента">
    <div>
      <strong>{String(payload.title ?? 'Требуется разрешение')}</strong>
      <small>{String(payload.detail ?? '')}</small>
      {resolved ? <p role="status">{status}</p> : <>
        <div className="permission-actions">
          <button type="button" className="button secondary small" disabled={pending} onClick={() => void reply(false)}>Отклонить</button>
          <button type="button" className="button primary small" disabled={pending} onClick={() => void reply(true)}>Разрешить один раз</button>
          <button type="button" className="button secondary small" disabled={pending || !canSave}
            title={canSave ? scope : 'OpenCode не предложил сохраняемое правило для этого запроса'}
            onClick={() => void reply(true, true)}>Разрешать всегда</button>
        </div>
        {canSave && <small className="permission-scope">«Разрешать всегда»: {scope.toLowerCase()}, для этого действия и ресурсов: <code>{resources.join(', ')}</code>.</small>}
        {pending && <p role="status">Отправляем решение…</p>}
        {error && <p className="permission-error" role="alert">{error}</p>}
      </>}
    </div>
  </section>
}
