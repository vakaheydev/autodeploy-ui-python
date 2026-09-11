import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { ArrowLeft, Check, ChevronRight, MessageSquareText, Plus, Search, Trash2, X } from './Icons'
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

export function ITSMPromptSettings({
  focusTarget = '',
  onDocumentChange,
}: {
  focusTarget?: string
  onDocumentChange?: (document: ITSMPromptSettingsDocument) => void
}) {
  const [document, setDocument] = useState<ITSMPromptSettingsDocument | null>(null)
  const [draft, setDraft] = useState<ITSMPromptRule[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [errors, setErrors] = useState<Record<number, { ticket_type?: string; prompt?: string }>>({})
  const [query, setQuery] = useState('')
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null)

  const apply = (next: ITSMPromptSettingsDocument) => {
    setDocument(next)
    setDraft(editable(next))
    setErrors({})
    onDocumentChange?.(next)
  }

  useEffect(() => {
    const controller = new AbortController()
    api<ITSMPromptSettingsDocument>('/api/v1/settings/itsm-ai-prompts', { signal: controller.signal })
      .then(apply)
      .catch((reason: unknown) => !controller.signal.aborted && setError(reason instanceof Error ? reason.message : String(reason)))
      .finally(() => !controller.signal.aborted && setLoading(false))
    return () => controller.abort()
  }, [])

  useEffect(() => {
    const match = /^itsm-(?:ticket-type|prompt)-(\d+)$/.exec(focusTarget)
    if (!match || loading) return
    const index = Number(match[1])
    if (!Number.isInteger(index) || index < 0 || index >= draft.length) return
    setSelectedIndex(index)
    const focus = (remaining: number) => {
      const element = window.document.getElementById(focusTarget) as HTMLInputElement | HTMLTextAreaElement | null
      if (!element && remaining > 0) return window.setTimeout(() => focus(remaining - 1), 40)
      element?.scrollIntoView?.({ behavior: 'smooth', block: 'center' })
      element?.focus({ preventScroll: true })
      element?.select()
    }
    window.setTimeout(() => focus(15), 0)
  }, [draft.length, focusTarget, loading])

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
    setSelectedIndex((current) => current === null ? null : current === index ? null : current > index ? current - 1 : current)
    setErrors({})
    setError('')
    setNotice('')
  }

  const save = async () => {
    if (!document) return
    const validation = ruleErrors(draft)
    if (Object.keys(validation).length > 0) {
      setErrors(validation)
      const index = Number(Object.keys(validation)[0])
      setSelectedIndex(index)
      const target = validation[index]?.ticket_type ? `itsm-ticket-type-${index}` : `itsm-prompt-${index}`
      window.setTimeout(() => {
        const element = window.document.getElementById(target) as HTMLInputElement | HTMLTextAreaElement | null
        element?.scrollIntoView?.({ behavior: 'smooth', block: 'center' })
        element?.focus({ preventScroll: true })
      }, 0)
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

  const words = query.trim().toLocaleLowerCase('ru').replace(/ё/g, 'е').split(/\s+/).filter(Boolean)
  const visibleRules = draft
    .map((rule, index) => ({ rule, index }))
    .filter(({ rule }) => {
      const haystack = `${rule.ticket_type} ${rule.prompt}`.toLocaleLowerCase('ru').replace(/ё/g, 'е')
      return words.every((word) => haystack.includes(word))
    })
  const selectedRule = selectedIndex === null ? null : draft[selectedIndex]
  const selectedOriginal = selectedIndex === null ? undefined : document.rules[selectedIndex]
  const selectedChanged = Boolean(selectedRule && (!selectedOriginal || JSON.stringify(selectedOriginal) !== JSON.stringify(selectedRule)))

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
        onClick={() => { const index = draft.length; setDraft((current) => [...current, { ticket_type: '', prompt: '' }]); setSelectedIndex(index); setNotice('') }}
      ><Plus size={16} /> Добавить тип</button>
    </div>
    <div className="settings-security-note"><MessageSquareText size={22} /><div><strong>Это доверенные инструкции</strong><p>Пишите только статические правила маппинга. Не вставляйте текст заявки, токены, URL с credentials или персональные данные.</p></div></div>
    {selectedRule && selectedIndex !== null ? <section className="itsm-prompt-editor">
      <header><button type="button" className="button ghost" onClick={() => setSelectedIndex(null)}><ArrowLeft size={16} /> К списку Ticket Type</button><span>{selectedChanged ? 'Есть несохранённые изменения' : 'Правило сохранено'}</span></header>
      <article className={`itsm-prompt-card editor ${selectedChanged ? 'changed' : ''} ${errors[selectedIndex] ? 'invalid' : ''}`}>
        <header><div><span>Ticket Type</span><small>{selectedChanged ? 'изменено' : 'сохранено'}</small></div><button type="button" className="button danger small" onClick={() => removeRule(selectedIndex)}><Trash2 size={15} /> Удалить</button></header>
        <label><span>Стабильный ticket_type</span><input id={`itsm-ticket-type-${selectedIndex}`} className="text-control itsm-prompt-control" aria-label={`Стабильный ticket_type ${selectedIndex + 1}`} value={selectedRule.ticket_type} maxLength={document.max_ticket_type_chars} aria-invalid={Boolean(errors[selectedIndex]?.ticket_type)} placeholder="Например, create_api_v2" onChange={(event) => updateRule(selectedIndex, { ticket_type: event.target.value })} />{errors[selectedIndex]?.ticket_type && <small className="configuration-error" role="alert"><X size={13} />{errors[selectedIndex].ticket_type}</small>}</label>
        <label><span>Prompt для AI</span><textarea id={`itsm-prompt-${selectedIndex}`} className="text-control itsm-prompt-control" aria-label={`Prompt для AI ${selectedIndex + 1}`} value={selectedRule.prompt} maxLength={document.max_prompt_chars} rows={12} aria-invalid={Boolean(errors[selectedIndex]?.prompt)} placeholder="Опишите правила сопоставления полей для этого типа заявки…" onChange={(event) => updateRule(selectedIndex, { prompt: event.target.value })} /><small className="itsm-prompt-counter">{selectedRule.prompt.length.toLocaleString('ru-RU')} / {document.max_prompt_chars.toLocaleString('ru-RU')}</small>{errors[selectedIndex]?.prompt && <small className="configuration-error" role="alert"><X size={13} />{errors[selectedIndex].prompt}</small>}</label>
      </article>
    </section> : <section className="itsm-prompt-catalog">
      <label className="itsm-prompt-search"><Search size={18} /><input className="text-control" aria-label="Поиск Ticket Type" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Найти Ticket Type или текст инструкции…" />{query && <button type="button" className="icon-button" aria-label="Очистить поиск Ticket Type" onClick={() => setQuery('')}><X size={14} /></button>}<small>{visibleRules.length} из {draft.length}</small></label>
      {draft.length === 0 && <div className="empty-state compact"><span className="empty-orb" /><h3>Переопределений пока нет</h3><p>AI использует инструкции, которые возвращает корпоративный <code>get_ai_prompt</code>.</p></div>}
      {draft.length > 0 && visibleRules.length === 0 && <div className="empty-state compact"><Search size={25} /><h3>Ticket Type не найден</h3><p>Измените поисковый запрос.</p></div>}
      <div className="itsm-prompt-list">{visibleRules.map(({ rule, index }) => { const original = document.rules[index]; const ruleChanged = !original || JSON.stringify(original) !== JSON.stringify(rule); return <button type="button" className={`itsm-prompt-summary ${ruleChanged ? 'changed' : ''} ${errors[index] ? 'invalid' : ''}`} key={`${index}-${original?.ticket_type ?? 'new'}`} aria-label={`Открыть Ticket Type ${rule.ticket_type || index + 1}`} onClick={() => setSelectedIndex(index)}><span className="itsm-prompt-summary-icon"><MessageSquareText size={19} /></span><span><small>Ticket Type</small><strong>{rule.ticket_type || 'Новый тип заявки'}</strong><p>{rule.prompt || 'Инструкция ещё не задана'}</p></span>{ruleChanged && <em>изменено</em>}<ChevronRight size={18} /></button> })}</div>
    </section>}
    {changed && <footer className="settings-actions"><button className="button secondary" disabled={saving} onClick={() => apply(document)}><X size={16} /> Сбросить правки</button><button className="button primary large" disabled={saving} onClick={() => void save()}><Check size={17} /> {saving ? 'Сохраняю…' : 'Сохранить ITSM AI-правила'}</button></footer>}
  </section>
}
