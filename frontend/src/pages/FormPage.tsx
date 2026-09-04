import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { api, post } from '../api'
import { ArrowLeft, Check, FileJson, LoaderCircle, RefreshCw, Send, Sparkles, X } from '../components/Icons'
import { ErrorBanner, Modal, Spinner } from '../components/Feedback'
import { FormFields } from '../components/FormFields'
import { useEnvironment } from '../environment'
import type { FormDocument, PreviewResult, SubmitResult, ValidationError, ValidationResult } from '../types'

interface LocationState { values?: Record<string, unknown>; handoffToken?: string; draftId?: string }
interface AIFieldResult { key: string; proposed_value: unknown; confidence: string; source?: string | null; reason?: string | null; conflict?: string | null }
interface ExtractionResult { values: Record<string, unknown>; baseline?: Record<string, unknown>; fields: AIFieldResult[]; warnings: string[]; errors?: ValidationError[]; valid?: boolean }
interface ExtractionState { id: string; workflow_id?: string; form_id?: string; environment?: string; status: string; progress: string; result: ExtractionResult | null; error: string }
interface ReviewEntry { confidence: string; proposedValue: unknown; source?: string | null; reason?: string | null; conflict?: string | null }
type AIResource = 'draft' | 'extraction' | null

function pathValue(source: Record<string, unknown>, path: string): { present: boolean; value: unknown } {
  const parts = path.split('.').filter(Boolean)
  let current: unknown = source
  for (const part of parts) {
    if (typeof current !== 'object' || current === null || Array.isArray(current) || !(part in current)) return { present: false, value: undefined }
    current = (current as Record<string, unknown>)[part]
  }
  return { present: true, value: current }
}

export function restorePath(current: Record<string, unknown>, baseline: Record<string, unknown>, path: string) {
  const parts = path.split('.').filter(Boolean)
  if (!parts.length) return current
  const restored = pathValue(baseline, path)
  const root = { ...current }
  let target = root
  for (const part of parts.slice(0, -1)) {
    const child = target[part]
    const next = typeof child === 'object' && child !== null && !Array.isArray(child)
      ? { ...(child as Record<string, unknown>) }
      : {}
    target[part] = next
    target = next
  }
  const leaf = parts[parts.length - 1]
  if (restored.present) target[leaf] = restored.value
  else delete target[leaf]
  return root
}

export function setPathValue(current: Record<string, unknown>, path: string, value: unknown) {
  const parts = path.split('.').filter(Boolean)
  if (!parts.length) return current
  const root = { ...current }
  let target = root
  for (const part of parts.slice(0, -1)) {
    const child = target[part]
    const next = typeof child === 'object' && child !== null && !Array.isArray(child)
      ? { ...(child as Record<string, unknown>) }
      : {}
    target[part] = next
    target = next
  }
  target[parts[parts.length - 1]] = value
  return root
}

export function applyReviewDecision(
  current: Record<string, unknown>,
  baseline: Record<string, unknown>,
  paths: string[],
  accept: boolean,
) {
  if (accept) return current
  return paths.reduce(
    (next, path) => restorePath(next, baseline, path),
    current,
  )
}

function reviewEntries(result: ExtractionResult, includeEmpty: boolean): Record<string, ReviewEntry> {
  return Object.fromEntries(result.fields
    .filter((field) => includeEmpty || (field.proposed_value !== null && field.proposed_value !== undefined))
    .map((field) => [field.key, {
      confidence: field.confidence,
      proposedValue: field.proposed_value,
      source: field.source,
      reason: field.reason,
      conflict: field.conflict,
    }]))
}

export function FormPage() {
  const { formId = '' } = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const restored = (location.state as LocationState | null)?.values
  const handoffToken = (location.state as LocationState | null)?.handoffToken
  const draftId = (location.state as LocationState | null)?.draftId
  const { environment, setEnvironment } = useEnvironment()
  const [document, setDocument] = useState<FormDocument | null>(null)
  const [values, setValues] = useState<Record<string, unknown>>({})
  const [errors, setErrors] = useState<ValidationError[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [preview, setPreview] = useState<PreviewResult | null>(null)
  const [previewMode, setPreviewMode] = useState<'inspect' | 'submit'>('inspect')
  const [ticketModal, setTicketModal] = useState(false)
  const [ticketId, setTicketId] = useState('')
  const [result, setResult] = useState<SubmitResult | null>(null)
  const stateSequence = useRef(0)
  const handoffStarted = useRef('')
  const draftStarted = useRef('')
  const extractionId = useRef('')
  const loadedScope = useRef('')
  const [extraction, setExtraction] = useState<ExtractionState | null>(null)
  const [aiResource, setAIResource] = useState<AIResource>(null)
  const [review, setReview] = useState<Record<string, ReviewEntry>>({})
  const [reviewBaseline, setReviewBaseline] = useState<Record<string, unknown>>({})
  const [refineModal, setRefineModal] = useState(false)
  const [guidance, setGuidance] = useState('')
  const [actionConfirm, setActionConfirm] = useState<{ id: string; text: string; token: string } | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    const scope = `${formId}|${environment}|${location.key}`
    loadedScope.current = ''
    if (extractionId.current) {
      void api(`/api/v1/ai/extractions/${encodeURIComponent(extractionId.current)}?cancel=true`, { method: 'DELETE' }).catch(() => undefined)
      extractionId.current = ''
    }
    handoffStarted.current = ''
    draftStarted.current = ''
    setExtraction(null)
    setAIResource(null)
    setReview({})
    setLoading(true)
    setError('')
    api<FormDocument>(`/api/v1/forms/${encodeURIComponent(formId)}?environment=${encodeURIComponent(environment)}`, { signal: controller.signal })
      .then((value) => {
        loadedScope.current = scope
        setDocument(value)
        setValues(restored ? { ...value.initial_values, ...restored } : value.initial_values)
        setErrors([])
        setResult(null)
      })
      .catch((reason: unknown) => !controller.signal.aborted && setError(reason instanceof Error ? reason.message : String(reason)))
      .finally(() => !controller.signal.aborted && setLoading(false))
    return () => controller.abort()
  }, [environment, formId, location.key])

  useEffect(() => () => {
    if (extractionId.current) {
      void fetch(`/api/v1/ai/extractions/${encodeURIComponent(extractionId.current)}?cancel=true`, { method: 'DELETE', keepalive: true })
      extractionId.current = ''
    }
  }, [])

  useEffect(() => {
    const scope = `${formId}|${environment}|${location.key}`
    const operation = `${handoffToken ?? ''}|${scope}`
    if (!document || draftId || !handoffToken || loadedScope.current !== scope || handoffStarted.current === operation) return
    handoffStarted.current = operation
    const baseline = { ...values }
    setReviewBaseline(baseline)
    setBusy(true)
    post<{ job_id: string }>(`/api/v1/ai/handoffs/${encodeURIComponent(handoffToken)}/extract`, {
      environment,
      current_values: baseline,
    }).then(({ job_id }) => {
      extractionId.current = job_id
      setAIResource('extraction')
      setExtraction({ id: job_id, status: 'pending', progress: 'Подготавливаю AI-предложения…', result: null, error: '' })
    })
      .catch((reason: unknown) => { setBusy(false); setError(reason instanceof Error ? reason.message : String(reason)) })
  }, [document, environment, formId, handoffToken, draftId, location.key])

  useEffect(() => {
    const scope = `${formId}|${environment}|${location.key}`
    const operation = `${draftId ?? ''}|${scope}`
    if (!document || !draftId || loadedScope.current !== scope || draftStarted.current === operation) return
    draftStarted.current = operation
    setBusy(true)
    api<ExtractionState>(`/api/v1/ai/drafts/${encodeURIComponent(draftId)}`)
      .then((next) => {
        if (next.form_id && next.form_id !== formId) throw new Error('AI-черновик относится к другой форме')
        if (next.environment && next.environment !== environment) {
          draftStarted.current = ''
          setEnvironment(next.environment)
          return
        }
        setAIResource('draft')
        setExtraction(next)
        if (next.result) {
          const baseline = next.result.baseline ?? { ...values }
          setReviewBaseline(baseline)
          setValues((current) => ({ ...current, ...next.result!.values }))
          setReview(reviewEntries(next.result, true))
          setErrors(next.result.errors ?? [])
        }
        if (next.status === 'complete') setBusy(false)
        if (['error', 'cancelled'].includes(next.status)) {
          setBusy(false)
          setError(next.error || 'AI-черновик завершился ошибкой')
        }
      })
      .catch((reason: unknown) => { setBusy(false); setError(reason instanceof Error ? reason.message : String(reason)) })
  }, [document, draftId, environment, formId, location.key, setEnvironment])

  useEffect(() => {
    if (!extraction || !['pending', 'running'].includes(extraction.status)) return
    const timer = window.setInterval(() => {
      const endpoint = aiResource === 'draft'
        ? `/api/v1/ai/drafts/${encodeURIComponent(extraction.id)}`
        : `/api/v1/ai/extractions/${encodeURIComponent(extraction.id)}`
      api<ExtractionState>(endpoint)
        .then((next) => {
          setExtraction(next)
          if (next.status === 'complete' && next.result) {
            if (next.result.baseline) setReviewBaseline(next.result.baseline)
            setValues((current) => ({ ...current, ...next.result!.values }))
            setReview(reviewEntries(next.result, aiResource === 'draft'))
            setErrors(next.result.errors ?? [])
            setBusy(false)
          } else if (['error', 'cancelled'].includes(next.status)) {
            setBusy(false); setError(next.error || 'AI-операция завершилась ошибкой')
          }
        })
        .catch((reason: unknown) => { window.clearInterval(timer); setBusy(false); setError(reason instanceof Error ? reason.message : String(reason)) })
    }, 700)
    return () => window.clearInterval(timer)
  }, [aiResource, extraction?.id, extraction?.status])

  useEffect(() => {
    if (!document || loading) return
    const sequence = ++stateSequence.current
    const timer = window.setTimeout(() => {
      post<FormDocument>(`/api/v1/forms/${encodeURIComponent(formId)}/state`, {
        environment,
        values,
        form_version: document.version,
      }).then((next) => {
        if (sequence === stateSequence.current) setDocument(next)
      }).catch((reason: unknown) => {
        if (sequence === stateSequence.current) setError(reason instanceof Error ? reason.message : String(reason))
      })
    }, 160)
    return () => window.clearTimeout(timer)
  }, [values, environment, formId, document?.version])

  useEffect(() => {
    if (!result?.polling || !result.poll_interval_ms) return
    let active = true
    const timer = window.setInterval(() => {
      post<{ polling: boolean; status: SubmitResult['status']; content: string; info?: string }>(`/api/v1/submissions/${result.submission_id}/poll`, {})
        .then((poll) => active && setResult((current) => current ? { ...current, polling: poll.polling, status: poll.status, content: poll.content + (poll.info ? `\n\n${poll.info}` : '') } : current))
        .catch((reason: unknown) => active && setError(reason instanceof Error ? reason.message : String(reason)))
    }, Math.max(500, result.poll_interval_ms))
    return () => { active = false; window.clearInterval(timer) }
  }, [result?.submission_id, result?.polling, result?.poll_interval_ms])

  const requestPreview = async (mode: 'inspect' | 'submit') => {
    if (!document) return
    setBusy(true)
    setError('')
    setErrors([])
    try {
      const value = await post<PreviewResult>(`/api/v1/forms/${encodeURIComponent(formId)}/preview`, {
        environment,
        values,
        form_version: document.version,
      })
      if (!value.valid) {
        setErrors(value.errors)
        setValues(value.values)
        return
      }
      setPreviewMode(mode)
      setPreview(value)
      if (mode === 'submit' && !value.confirmation_required) await executeSubmit(value)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusy(false)
    }
  }

  const executeSubmit = async (prepared = preview) => {
    if (!document || !prepared) return
    setBusy(true)
    setError('')
    try {
      const submitted = await post<SubmitResult>(`/api/v1/forms/${encodeURIComponent(formId)}/submit`, {
        environment,
        values: prepared.values,
        form_version: document.version,
        confirmation_token: prepared.confirmation_token ?? '',
      })
      setValues(prepared.values)
      setResult(submitted)
      setPreview(null)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusy(false)
    }
  }

  const fetchTicket = async () => {
    if (!document || !ticketId.trim()) return
    setBusy(true)
    setError('')
    try {
      const response = await post<{ values: Record<string, unknown>; errors: ValidationError[] }>(`/api/v1/forms/${encodeURIComponent(formId)}/ticket`, {
        environment,
        ticket_id: ticketId.trim(),
      })
      setValues((current) => ({ ...current, ...response.values }))
      setErrors(response.errors)
      setTicketModal(false)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusy(false)
    }
  }

  const closeAIResource = async (cancel = false) => {
    if (!extraction) return
    if (aiResource === 'draft') {
      await api(`/api/v1/ai/drafts/${encodeURIComponent(extraction.id)}`, {
        method: 'DELETE',
      }).catch(() => undefined)
    } else {
      await api(`/api/v1/ai/extractions/${encodeURIComponent(extraction.id)}?cancel=${cancel ? 'true' : 'false'}`, {
        method: 'DELETE',
      }).catch(() => undefined)
      extractionId.current = ''
    }
    setExtraction(null)
    setAIResource(null)
  }

  const stopAI = async () => {
    if (!extraction) return
    if (aiResource === 'draft' && extraction.workflow_id) {
      await post(`/api/v1/ai/sessions/${encodeURIComponent(extraction.workflow_id)}/cancel`, {}).catch(() => undefined)
      return
    }
    await closeAIResource(true)
    setBusy(false)
  }

  const closeCompletedReview = async (finalValues: Record<string, unknown>) => {
    if (!document) return
    setBusy(true); setError('')
    try {
      const validation = await post<ValidationResult>(`/api/v1/forms/${encodeURIComponent(formId)}/validate`, {
        environment, values: finalValues, form_version: document.version,
      })
      setValues(validation.values)
      setErrors(validation.errors)
      await closeAIResource()
      navigate(location.pathname, { replace: true, state: { values: validation.values } })
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusy(false)
    }
  }

  const decideReview = (key: string, accept: boolean) => {
    const proposal = review[key]
    if (!proposal) return
    // The proposal is already visible in the live form.  A user may edit it
    // before approving, so approval keeps the current value rather than
    // restoring the original AI suggestion.
    const nextValues = applyReviewDecision(values, reviewBaseline, [key], accept)
    const nextReview = { ...review }
    delete nextReview[key]
    setValues(nextValues)
    setReview(nextReview)
    setErrors((current) => current.filter((item) => item.field !== key))
    if (!Object.keys(nextReview).length) void closeCompletedReview(nextValues)
  }

  const finishReview = async (accept: boolean) => {
    if (!document) return
    const finalValues = applyReviewDecision(
      values,
      reviewBaseline,
      Object.keys(review),
      accept,
    )
    setBusy(true); setError('')
    try {
      const validation = await post<ValidationResult>(`/api/v1/forms/${encodeURIComponent(formId)}/validate`, {
        environment,
        values: finalValues,
        form_version: document.version,
      })
      setValues(validation.values)
      setErrors(validation.errors)
      setReview({})
      await closeAIResource()
      navigate(location.pathname, { replace: true, state: { values: validation.values } })
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusy(false)
    }
  }

  const refine = async () => {
    if (!extraction || !guidance.trim()) return
    setBusy(true); setRefineModal(false); setError('')
    try {
      const endpoint = aiResource === 'draft'
        ? `/api/v1/ai/drafts/${encodeURIComponent(extraction.id)}/refine`
        : `/api/v1/ai/extractions/${encodeURIComponent(extraction.id)}/refine`
      const body = aiResource === 'draft'
        ? { guidance: guidance.trim(), current_values: values, pending_fields: Object.keys(review) }
        : { guidance: guidance.trim() }
      const next = await post<ExtractionState>(endpoint, body)
      setExtraction(next); setGuidance('')
    } catch (reason) { setBusy(false); setError(reason instanceof Error ? reason.message : String(reason)) }
  }

  const runAction = async (actionId: string, confirmationToken = '') => {
    if (!document) return
    setBusy(true); setError('')
    try {
      const response = await post<{ success: boolean; message?: string; values?: Record<string, unknown>; confirmation_required?: boolean; confirmation_text?: string; confirmation_token?: string; validation?: { errors?: ValidationError[] } }>(`/api/v1/forms/${encodeURIComponent(formId)}/actions/${encodeURIComponent(actionId)}`, {
        environment, values, form_version: document.version, confirmation_token: confirmationToken,
      })
      if (response.confirmation_required && response.confirmation_token) {
        setActionConfirm({ id: actionId, text: response.confirmation_text ?? 'Подтвердите действие', token: response.confirmation_token })
      } else if (!response.success) {
        setErrors(response.validation?.errors ?? [])
        setError(response.message ?? 'Действие не выполнено')
      } else {
        if (response.values) setValues((current) => ({ ...current, ...response.values }))
        setActionConfirm(null)
        if (response.message) setResult({ success: true, message: response.message, submission_id: '', status: 'success', title: 'Действие выполнено', content: '', response: null, payload: null, polling: false, poll_interval_ms: null })
      }
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) } finally { setBusy(false) }
  }

  if (loading) return <Spinner label="Загружаю описание Python-формы…" />
  if (!document) return <div className="page-stack"><ErrorBanner message={error || 'Форма не найдена'} /><Link to="/forms" className="button secondary"><ArrowLeft size={16} /> К каталогу</Link></div>

  return (
    <div className="form-page">
      <div className="form-header">
        <div>
          <Link to="/forms" className="back-link"><ArrowLeft size={16} /> Каталог форм</Link>
          <span className="eyebrow">{document.category_label}</span>
          <h1>{document.title}</h1>
          <p><code>{document.id}</code> · версия схемы {document.version.slice(0, 8)}</p>
        </div>
        <span className="server-badge"><span className="status-dot online" /> Python runtime</span>
      </div>

      {error && <ErrorBanner message={error} onClose={() => setError('')} />}
      {extraction && ['pending', 'running'].includes(extraction.status) && <div className="ai-extraction-banner"><span className="ai-spinner"><Sparkles /></span><div><strong>Copilot обновляет предложения</strong><span>{extraction.progress}</span></div><button className="button ghost small" onClick={() => void stopAI()}>Остановить</button></div>}
      {extraction?.result?.warnings.length ? <div className="alert warning"><div>{extraction.result.warnings.map((warning) => <p key={warning}>{warning}</p>)}</div></div> : null}
      {errors.some((item) => !item.field) && <div className="alert error"><div>{errors.filter((item) => !item.field).map((item) => <p key={item.message}>{item.message}</p>)}</div></div>}

      <section className="form-surface">
        <FormFields
          fields={document.fields}
          values={values}
          environment={environment}
          formId={formId}
          errors={errors}
          disabled={busy}
          onValuesChange={(next) => { setValues(next); setErrors((current) => current.filter((item) => !item.field)) }}
          review={review}
          onReview={decideReview}
        />
      </section>

      {document.custom_actions.length > 0 && <section className="legacy-actions"><strong>Дополнительные действия</strong>{document.custom_actions.map((action) => <button className={`button ${action.style.toLowerCase() === 'primary' ? 'primary' : 'secondary'}`} disabled={!action.available || busy} title={action.reason} onClick={() => void runAction(action.id)} key={action.id}>{action.label}</button>)}</section>}

      {result && <section className={`result-card ${result.status}`}>
        <div className="result-icon">{result.status === 'success' ? <Check /> : result.status === 'error' ? <X /> : <LoaderCircle className={result.polling ? 'spin' : ''} />}</div>
        <div><span className="eyebrow">Результат операции</span><h2>{result.title}</h2><p>{result.message}</p><pre>{result.content}</pre>{result.polling && <small>Статус обновляется автоматически</small>}</div>
      </section>}

      <footer className={`form-actions ${Object.keys(review).length ? 'reviewing' : ''}`}>
        {Object.keys(review).length ? <><div className="review-summary"><Sparkles size={18} /><span><strong>Проверьте AI-предложения</strong><small>{Object.keys(review).length} ожидают решения</small></span></div><div className="button-row"><button className="button secondary" disabled={busy} onClick={() => setRefineModal(true)}><Sparkles size={17} /> Уточнить</button><button className="button danger" disabled={busy} onClick={() => void finishReview(false)}><X size={17} /> Отклонить всё</button><button className="button success" disabled={busy} onClick={() => void finishReview(true)}><Check size={17} /> Принять всё</button></div></> : <>
        <div className="form-actions-secondary">
          <button className="button secondary" disabled={busy} onClick={() => void requestPreview('inspect')}><FileJson size={17} /> Просмотр JSON</button>
          {document.itsm_support && <button className="button secondary" disabled={busy} onClick={() => setTicketModal(true)}><Sparkles size={17} /> Подтянуть заявку</button>}
          <button className="button ghost" disabled={busy} onClick={() => { setValues(document.initial_values); setErrors([]); setResult(null) }}><RefreshCw size={16} /> Сбросить</button>
        </div>
        <button className="button primary large" disabled={busy} onClick={() => void requestPreview('submit')}>{busy ? <LoaderCircle className="spin" size={18} /> : <Send size={18} />} Отправить</button>
        </>}
      </footer>

      {preview && <Modal
        title={previewMode === 'submit' && preview.confirmation_required ? 'Подтвердите операцию' : 'Предварительный просмотр'}
        onClose={() => setPreview(null)}
        footer={<><button className="button secondary" onClick={() => setPreview(null)}>Закрыть</button>{previewMode === 'submit' && <button className="button primary" disabled={busy} onClick={() => void executeSubmit()}><Check size={17} /> Подтвердить и отправить</button>}</>}
      >
        {preview.confirmation_text && <pre className="confirm-text">{preview.confirmation_text}</pre>}
        {!preview.confirmation_text && <pre className="json-preview">{JSON.stringify(preview.payload, null, 2)}</pre>}
      </Modal>}

      {ticketModal && <Modal title="Подтянуть данные из заявки" onClose={() => setTicketModal(false)} footer={<><button className="button secondary" onClick={() => setTicketModal(false)}>Отмена</button><button className="button primary" disabled={busy || !ticketId.trim()} onClick={() => void fetchTicket()}><Sparkles size={17} /> Получить данные</button></>}>
        <label className="form-field"><span className="field-label">Номер заявки</span><input autoFocus value={ticketId} onChange={(event) => setTicketId(event.target.value)} placeholder="REQ-123456" onKeyDown={(event) => event.key === 'Enter' && void fetchTicket()} /></label>
      </Modal>}
      {refineModal && <Modal title="Уточнить AI-предложения" onClose={() => setRefineModal(false)} footer={<><button className="button secondary" onClick={() => setRefineModal(false)}>Отмена</button><button className="button primary" disabled={!guidance.trim()} onClick={() => void refine()}><Sparkles size={17} /> Отправить агенту</button></>}><label className="form-field"><span className="field-label">Что нужно изменить?</span><textarea rows={6} autoFocus value={guidance} onChange={(event) => setGuidance(event.target.value)} placeholder="Например: оставь текущего владельца, а context path замени на /payments/v2" /></label></Modal>}
      {actionConfirm && <Modal title="Подтвердите дополнительное действие" onClose={() => setActionConfirm(null)} footer={<><button className="button secondary" onClick={() => setActionConfirm(null)}>Отмена</button><button className="button primary" disabled={busy} onClick={() => void runAction(actionConfirm.id, actionConfirm.token)}><Check size={17} /> Подтвердить</button></>}><p>{actionConfirm.text}</p></Modal>}
    </div>
  )
}
