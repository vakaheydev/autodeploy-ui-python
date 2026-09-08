import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, post } from '../api'
import { ArrowLeft, Check, LoaderCircle, Puzzle, X } from '../components/Icons'
import { ErrorBanner, Modal, Spinner } from '../components/Feedback'
import { FormFields } from '../components/FormFields'
import { PluginWidgets } from '../components/PluginWidgets'
import { useEnvironment } from '../environment'
import type { PluginActionResponse, PluginDocument, PluginOperationDocument, ValidationError } from '../types'

export function PluginPage() {
  const { pluginId = '' } = useParams()
  const { environment } = useEnvironment()
  const [document, setDocument] = useState<PluginDocument | null>(null)
  const [values, setValues] = useState<Record<string, unknown>>({})
  const [errors, setErrors] = useState<ValidationError[]>([])
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [loading, setLoading] = useState(true)
  const [busyOperation, setBusyOperation] = useState('')
  const [confirmation, setConfirmation] = useState<{ operation: PluginOperationDocument; text: string; token: string } | null>(null)
  const stateSequence = useRef(0)
  const initialized = useRef(false)
  const skipNextState = useRef(false)

  useEffect(() => {
    const controller = new AbortController()
    initialized.current = false
    setLoading(true); setError(''); setNotice(''); setErrors([])
    api<PluginDocument>(`/api/v1/plugins/${encodeURIComponent(pluginId)}?environment=${encodeURIComponent(environment)}`, { signal: controller.signal })
      .then((next) => {
        skipNextState.current = true
        setDocument(next)
        setValues(next.initial_values)
        initialized.current = true
      })
      .catch((reason: unknown) => !controller.signal.aborted && setError(reason instanceof Error ? reason.message : String(reason)))
      .finally(() => !controller.signal.aborted && setLoading(false))
    return () => controller.abort()
  }, [environment, pluginId])

  useEffect(() => {
    if (!document || !initialized.current || busyOperation) return
    if (skipNextState.current) {
      skipNextState.current = false
      return
    }
    const sequence = ++stateSequence.current
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      post<PluginDocument>(`/api/v1/plugins/${encodeURIComponent(pluginId)}/state`, {
        environment,
        values,
        plugin_version: document.version,
      }, controller.signal).then((next) => {
        if (sequence !== stateSequence.current) return
        setError('')
        setDocument(next)
        setValues((current) => (
          JSON.stringify(current) === JSON.stringify(next.initial_values)
            ? current
            : next.initial_values
        ))
      }).catch((reason: unknown) => {
        if (!controller.signal.aborted && sequence === stateSequence.current) setError(reason instanceof Error ? reason.message : String(reason))
      })
    }, 200)
    return () => { window.clearTimeout(timer); controller.abort() }
  }, [values, environment, pluginId, document?.version, busyOperation])

  const execute = async (operation: PluginOperationDocument, token = '') => {
    if (!document) return
    setBusyOperation(operation.id); setError(''); setNotice('')
    try {
      const result = await post<PluginActionResponse>(`/api/v1/plugins/${encodeURIComponent(pluginId)}/operations/${encodeURIComponent(operation.id)}`, {
        environment,
        values,
        plugin_version: document.version,
        confirmation_token: token,
      })
      if (result.confirmation_required && result.confirmation_token) {
        setConfirmation({ operation, text: result.confirmation_text ?? 'Выполнить операцию?', token: result.confirmation_token })
        return
      }
      if (!result.success) {
        setErrors(result.validation?.errors ?? [])
        setError(result.message || 'Операция не выполнена')
        return
      }
      setConfirmation(null)
      skipNextState.current = true
      setValues(result.values ?? values)
      setDocument((current) => current ? {
        ...current,
        fields: result.fields ?? current.fields,
        widgets: result.widgets ?? current.widgets,
      } : current)
      setErrors(result.validation?.errors ?? [])
      setNotice(result.message || 'Операция выполнена')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusyOperation('')
    }
  }

  if (loading) return <Spinner label="Загружаю плагин…" />
  if (!document) return <div className="page-stack"><Link className="back-link" to="/plugins"><ArrowLeft size={15} /> Каталог плагинов</Link>{error && <ErrorBanner message={error} />}</div>

  return <div className="plugin-page page-stack">
    <div className="plugin-page-header"><div><Link className="back-link" to="/plugins"><ArrowLeft size={15} /> Каталог плагинов</Link><span className="eyebrow">{document.category}</span><h1><Puzzle size={30} /> {document.title}</h1>{document.description && <p>{document.description}</p>}</div><span className="server-badge"><Check size={15} /> Python plugin</span></div>
    {error && <ErrorBanner message={error} onClose={() => setError('')} />}
    {notice && <div className="alert success"><Check size={17} /><p>{notice}</p></div>}
    {document.fields.length > 0 && <section className="form-surface plugin-fields"><div className="section-heading"><div><h2>Параметры</h2><span>Логика исполняется на сервере</span></div></div><FormFields fields={document.fields} values={values} environment={environment} formId={document.id} errors={errors} disabled={Boolean(busyOperation)} onValuesChange={setValues} onFieldChange={(path) => setErrors((current) => current.filter((item) => item.field !== path))} /></section>}
    <PluginWidgets widgets={document.widgets} />
    {document.operations.length > 0 && <footer className="plugin-actions">{document.operations.map((operation) => <button type="button" className={`button ${operation.style || 'secondary'} large`} disabled={Boolean(busyOperation)} key={operation.id} onClick={() => void execute(operation)}>{busyOperation === operation.id ? <LoaderCircle className="spin" size={17} /> : <Puzzle size={16} />}{busyOperation === operation.id ? 'Выполняю…' : operation.label}</button>)}</footer>}
    {confirmation && <Modal title="Подтвердите операцию" onClose={() => !busyOperation && setConfirmation(null)} footer={<><button className="button secondary" disabled={Boolean(busyOperation)} onClick={() => setConfirmation(null)}><X size={15} /> Отмена</button><button className="button danger" disabled={Boolean(busyOperation)} onClick={() => void execute(confirmation.operation, confirmation.token)}>{busyOperation ? <LoaderCircle className="spin" size={16} /> : <Check size={16} />} Выполнить</button></>}><p className="plugin-confirmation">{confirmation.text}</p></Modal>}
  </div>
}
