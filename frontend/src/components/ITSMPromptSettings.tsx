import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { Check, MessageSquareText, Plus, Trash2, X } from './Icons'
import { ErrorBanner, Spinner } from './Feedback'
import type { ITSMPromptRule, ITSMPromptSettingsDocument } from '../types'

function editable(document: ITSMPromptSettingsDocument): ITSMPromptRule[] {
  return document.rules.map((rule) => ({ ...rule }))
}

function ruleErrors(rules: ITSMPromptRule[]): Record<number, { ticket_type?: string; prompt?: string }> {
  const errors: Record<number, { ticket_type?: string; prompt?: string }> = {}
  const seen = new Map<string, number>()
  rules.forEach((rule, index) => {
    const ticketType = rule.ticket_type.trim()
    const prompt = rule.prompt.trim()
    if (!ticketType) errors[index] = { ...errors[index], ticket_type: 'Укажите тип заявки.' }
    if (!prompt) errors[index] = { ...errors[index], prompt: 'Добавьте инструкции для AI.' }
    const identity = ticketType.toLocaleLowerCase()
    if (identity) {
      const previous = seen.get(identity)
      if (previous !== undefined) {
        errors[index] = { ...errors[index], ticket_type: 'Этот тип заявки уже настроен.' }
        errors[previous] = { ...errors[previous], ticket_type: 'Этот тип заявки уже настроен.' }
      } else {
        seen.set(identity, index)
      }
    }
  })
  return errors
}

export function ITSMPromptSettings() {
  const [document, setDocument] = useState<ITSMPromptSettingsDocument | null>(null)
  const [draft, setDraft] = useState<ITSMPromptRule[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [errors, setErrors] = useState<Record<number, { ticket_type?: string; prompt?: string }>>({})

  const apply = (next: ITSMPromptSettingsDocument) => {
    setDocument(next)
    setDraft(editable(next))
    setErrors({})
  }

  useEffect(() => {
    const controller = new AbortController()
    api<ITSMPromptSettingsDocument>('/api/v1/settings/itsm-ai-prompts', { signal: controller.signal })
      .then(apply)
      .catch((reason: unknown) => !controller.signal.aborted && setError(reason instanceof Error ? reason.message : String(reason)))
      .finally(() => !controller.signal.aborted && setLoading(false))
    return () => controller.abort()
  }, [])

  const changed = useMemo(
    () => Boolean(document && JSON.stringify(editable(document)) !== JSON.stringify(draft)),
    [document, draft],
  )

  const updateRule = (index: number, patch: Partial<ITSMPromptRule>) => {
    setDraft((current) => current.map((rule, ruleIndex) => ruleIndex === index ? { ...rule, ...patch } : rule))
    setErrors((current) => {
      if (!current[index]) return current
      const next = { ...current }
      delete next[index]
      return next
    })
    setError('')
    setNotice('')
  }

  const removeRule = (index: number) => {
    setDraft((current) => current.filter((_, ruleIndex) => ruleIndex !== index))
    setErrors({})
    setError('')
    setNotice('')
  }

  const save = async () => {
    if (!document) return
    const validation = ruleErrors(draft)
    if (Object.keys(validation).length > 0) {
      setErrors(validation)
      return
    }
    setSaving(true); setError(''); setNotice('')
    try {
      const next = await api<ITSMPromptSettingsDocument>('/api/v1/settings/itsm-ai-prompts', {
        method: 'PUT',
        body: JSON.stringify({ rules: draft }),
      })
      apply(next)
      setNotice('Правила сохранены и будут применены при следующей загрузке заявки в AI.')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <Spinner label="Загружаю ITSM AI-правила…" />
  if (!document) return error ? <ErrorBanner message={error} /> : null

  return <section className="itsm-prompt-settings">
    {error && <ErrorBanner message={error} onClose={() => setError('')} />}
    {document.warning && <ErrorBanner message={document.warning} />}
    {notice && <div className="alert success"><Check size={17} /><p>{notice}</p></div>}
    <div className="itsm-prompt-heading">
      <span className="plugin-policy-icon"><MessageSquareText size={22} /></span>
      <div>
        <h2>Инструкции по типам заявок</h2>
        <p>Корпоративный ITSM-service определяет стабильный <code>ticket_type</code>. Точное правило из этого списка заменяет prompt hook для такого типа; если правила нет, используется корпоративный prompt.</p>
      </div>
      <button
        type="button"
        className="button secondary"
        disabled={draft.length >= document.max_rules}
        onClick={() => { setDraft((current) => [...current, { ticket_type: '', prompt: '' }]); setNotice('') }}
      ><Plus size={16} /> Добавить тип</button>
    </div>
    <div className="settings-security-note"><MessageSquareText size={22} /><div><strong>Это доверенные инструкции</strong><p>Пишите только статические правила маппинга. Не вставляйте текст заявки, токены, URL с credentials или персональные данные.</p></div></div>
    {draft.length === 0 && <div className="empty-state compact"><span className="empty-orb" /><h3>Переопределений пока нет</h3><p>AI использует инструкции, которые возвращает корпоративный <code>get_ai_prompt</code>.</p></div>}
    <div className="itsm-prompt-list">
      {draft.map((rule, index) => {
        const original = document.rules[index]
        const ruleChanged = !original || JSON.stringify(original) !== JSON.stringify(rule)
        const fieldError = errors[index]
        return <article className={`itsm-prompt-card ${ruleChanged ? 'changed' : ''} ${fieldError ? 'invalid' : ''}`} key={`${index}-${original?.ticket_type ?? 'new'}`}>
          <header>
            <div><span>Тип заявки {index + 1}</span><small>{ruleChanged ? 'изменено' : 'сохранено'}</small></div>
            <button type="button" className="icon-button danger" title="Удалить правило" aria-label={`Удалить правило ${index + 1}`} onClick={() => removeRule(index)}><Trash2 size={16} /></button>
          </header>
          <label>
            <span>Стабильный ticket_type</span>
            <input
              className="itsm-prompt-control"
              aria-label={`Стабильный ticket_type ${index + 1}`}
              value={rule.ticket_type}
              maxLength={document.max_ticket_type_chars}
              aria-invalid={Boolean(fieldError?.ticket_type)}
              placeholder="Например, create_api_v2"
              onChange={(event) => updateRule(index, { ticket_type: event.target.value })}
            />
            {fieldError?.ticket_type && <small className="configuration-error" role="alert"><X size={13} />{fieldError.ticket_type}</small>}
          </label>
          <label>
            <span>Prompt для AI</span>
            <textarea
              className="itsm-prompt-control"
              aria-label={`Prompt для AI ${index + 1}`}
              value={rule.prompt}
              maxLength={document.max_prompt_chars}
              rows={7}
              aria-invalid={Boolean(fieldError?.prompt)}
              placeholder="Опишите правила сопоставления полей для этого типа заявки…"
              onChange={(event) => updateRule(index, { prompt: event.target.value })}
            />
            <small className="itsm-prompt-counter">{rule.prompt.length.toLocaleString('ru-RU')} / {document.max_prompt_chars.toLocaleString('ru-RU')}</small>
            {fieldError?.prompt && <small className="configuration-error" role="alert"><X size={13} />{fieldError.prompt}</small>}
          </label>
        </article>
      })}
    </div>
    {changed && <footer className="settings-actions"><button className="button secondary" disabled={saving} onClick={() => apply(document)}><X size={16} /> Сбросить правки</button><button className="button primary large" disabled={saving} onClick={() => void save()}><Check size={17} /> {saving ? 'Сохраняю…' : 'Сохранить ITSM AI-правила'}</button></footer>}
  </section>
}
