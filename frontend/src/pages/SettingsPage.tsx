import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { Check, KeyRound, ShieldCheck, X } from '../components/Icons'
import { ErrorBanner, Spinner } from '../components/Feedback'
import type { SettingField, SettingsDocument } from '../types'

function draftFrom(document: SettingsDocument): Record<string, string | boolean> {
  return Object.fromEntries(document.groups.flatMap((group) => group.fields.map((field) => [
    field.key,
    field.kind === 'secret' ? '' : field.value ?? '',
  ])))
}

export function SettingsPage() {
  const [document, setDocument] = useState<SettingsDocument | null>(null)
  const [draft, setDraft] = useState<Record<string, string | boolean>>({})
  const [changed, setChanged] = useState<Set<string>>(new Set())
  const [clear, setClear] = useState<Set<string>>(new Set())
  const [visibleSecrets, setVisibleSecrets] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const applyDocument = (next: SettingsDocument) => {
    setDocument(next)
    setDraft(draftFrom(next))
    setChanged(new Set())
    setClear(new Set())
    setVisibleSecrets(new Set())
  }

  useEffect(() => {
    const controller = new AbortController()
    api<SettingsDocument>('/api/v1/settings', { signal: controller.signal })
      .then(applyDocument)
      .catch((reason: unknown) => !controller.signal.aborted && setError(reason instanceof Error ? reason.message : String(reason)))
      .finally(() => !controller.signal.aborted && setLoading(false))
    return () => controller.abort()
  }, [])

  const fields = useMemo(() => document?.groups.flatMap((group) => group.fields) ?? [], [document])
  const fieldByKey = useMemo(() => new Map(fields.map((field) => [field.key, field])), [fields])

  const changeValue = (field: SettingField, value: string | boolean) => {
    setDraft((current) => ({ ...current, [field.key]: value }))
    setChanged((current) => new Set(current).add(field.key))
    setClear((current) => {
      const next = new Set(current)
      next.delete(field.key)
      return next
    })
    setNotice('')
  }

  const toggleClear = (field: SettingField) => {
    setClear((current) => {
      const next = new Set(current)
      next.has(field.key) ? next.delete(field.key) : next.add(field.key)
      return next
    })
    setChanged((current) => {
      const next = new Set(current)
      next.delete(field.key)
      return next
    })
    setDraft((current) => ({ ...current, [field.key]: '' }))
    setNotice('')
  }

  const save = async () => {
    if (!document) return
    setSaving(true); setError(''); setNotice('')
    const values = Object.fromEntries([...changed]
      .filter((key) => fieldByKey.get(key)?.kind !== 'secret' || String(draft[key] ?? '').length > 0)
      .map((key) => [key, draft[key]]))
    try {
      const next = await api<SettingsDocument>('/api/v1/settings', {
        method: 'PUT',
        body: JSON.stringify({ values, clear: [...clear] }),
      })
      const messages = ['Настройки сохранены.']
      if (next.reconnect_opencode) messages.push('Переподключите OpenCode.')
      if (next.restart_required) messages.push('Для части изменений перезапустите приложение.')
      setNotice(messages.join(' '))
      applyDocument(next)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <Spinner label="Загружаю настройки…" />

  return (
    <div className="page-stack settings-page">
      <div className="page-title"><div><span className="eyebrow">Server-side configuration</span><h1>Настройки</h1><p>Конфигурация хранится в локальном `.env`; секреты доступны только на запись.</p></div><span className="server-badge"><ShieldCheck size={16} /> Секреты скрыты API</span></div>
      {error && <ErrorBanner message={error} onClose={() => setError('')} />}
      {notice && <div className="alert success"><Check size={17} /><p>{notice}</p></div>}
      <div className="settings-security-note"><KeyRound size={22} /><div><strong>Сохранённые секреты не отправляются в браузер</strong><p>Пустое поле оставляет секрет без изменений. Для удаления используйте «Очистить».</p></div></div>
      {document?.groups.map((group) => (
        <section className="configuration-group" key={group.name}>
          <div className="section-heading"><div><h2>{group.name}</h2><span>{group.fields.length} параметров</span></div></div>
          <div className="configuration-grid">
            {group.fields.map((field) => {
              const isCleared = clear.has(field.key)
              const inputType = field.kind === 'secret' && !visibleSecrets.has(field.key) ? 'password' : field.kind === 'number' ? 'number' : 'text'
              return <label className={`configuration-field ${isCleared ? 'cleared' : ''}`} key={field.key}>
                <span className="configuration-label"><span>{field.label}{field.required && <b>*</b>}</span>{field.restart_required && <small>restart</small>}</span>
                {field.kind === 'boolean'
                  ? <span className="settings-switch"><input type="checkbox" checked={Boolean(draft[field.key])} onChange={(event) => changeValue(field, event.target.checked)} /><span className="switch" /><span>{Boolean(draft[field.key]) ? 'Включено' : 'Выключено'}</span></span>
                  : <span className="configuration-input"><input
                    type={inputType}
                    value={String(draft[field.key] ?? '')}
                    min={field.minimum ?? undefined}
                    max={field.maximum ?? undefined}
                    disabled={isCleared}
                    autoComplete="off"
                    placeholder={field.kind === 'secret' && field.configured ? '••••••••  настроено' : field.default || 'Не задано'}
                    onChange={(event) => changeValue(field, event.target.value)}
                  />{field.kind === 'secret' && <button type="button" className="button ghost small" onClick={() => setVisibleSecrets((current) => { const next = new Set(current); next.has(field.key) ? next.delete(field.key) : next.add(field.key); return next })}>{visibleSecrets.has(field.key) ? 'Скрыть' : 'Показать'}</button>}{field.kind === 'secret' && field.configured && <button type="button" className={`button small ${isCleared ? 'secondary' : 'danger'}`} onClick={() => toggleClear(field)}>{isCleared ? 'Отменить' : 'Очистить'}</button>}</span>}
                <span className="configuration-meta"><code>{field.key}</code>{field.description && <small>{field.description}</small>}{field.kind === 'secret' && <small className={field.configured && !isCleared ? 'configured' : ''}>{isCleared ? 'Будет удалён' : field.configured ? 'Секрет настроен' : 'Не настроен'}</small>}</span>
              </label>
            })}
          </div>
        </section>
      ))}
      <footer className="settings-actions"><button className="button secondary" disabled={saving || (!changed.size && !clear.size)} onClick={() => document && applyDocument(document)}><X size={16} /> Сбросить правки</button><button className="button primary large" disabled={saving || (!changed.size && !clear.size)} onClick={() => void save()}><Check size={17} /> {saving ? 'Сохраняю…' : 'Сохранить настройки'}</button></footer>
    </div>
  )
}
