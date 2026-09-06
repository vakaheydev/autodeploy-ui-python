import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { Check, KeyRound, RefreshCw, ShieldCheck, X } from '../components/Icons'
import { ErrorBanner, Spinner } from '../components/Feedback'
import { OpenCodeServerPanel } from '../components/OpenCodeServerPanel'
import { McpMultiPicker, McpSinglePicker, PathSettingPicker } from '../components/SettingsPickers'
import type { SettingField, SettingsDocument } from '../types'

function draftFrom(document: SettingsDocument): Record<string, string | boolean> {
  return Object.fromEntries(document.groups.flatMap((group) => group.fields.map((field) => [
    field.key,
    field.kind === 'secret' ? '' : field.value ?? '',
  ])))
}

export function SettingsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedGroup = searchParams.get('section')
  const [document, setDocument] = useState<SettingsDocument | null>(null)
  const [draft, setDraft] = useState<Record<string, string | boolean>>({})
  const [changed, setChanged] = useState<Set<string>>(new Set())
  const [clear, setClear] = useState<Set<string>>(new Set())
  const [visibleSecrets, setVisibleSecrets] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [activeGroup, setActiveGroup] = useState('')
  const [mcpItems, setMcpItems] = useState<Array<{ name: string; status: string; error: string }>>([])
  const [mcpConnected, setMcpConnected] = useState(false)
  const [mcpLoading, setMcpLoading] = useState(false)

  const applyDocument = (next: SettingsDocument) => {
    setDocument(next)
    setDraft(draftFrom(next))
    setChanged(new Set())
    setClear(new Set())
    setVisibleSecrets(new Set())
    setActiveGroup((current) => {
      if (current && next.groups.some((group) => group.name === current)) return current
      return requestedGroup && next.groups.some((group) => group.name === requestedGroup) ? requestedGroup : next.groups[0]?.name ?? ''
    })
  }

  const loadMcp = async () => {
    setMcpLoading(true)
    try {
      const result = await api<{ connected: boolean; items: Array<{ name: string; status: string; error: string }> }>('/api/v1/opencode/mcp')
      setMcpConnected(result.connected === true)
      setMcpItems(Array.isArray(result.items) ? result.items : [])
    } catch {
      setMcpConnected(false)
      setMcpItems([])
    } finally {
      setMcpLoading(false)
    }
  }

  useEffect(() => {
    const controller = new AbortController()
    api<SettingsDocument>('/api/v1/settings', { signal: controller.signal })
      .then(applyDocument)
      .catch((reason: unknown) => !controller.signal.aborted && setError(reason instanceof Error ? reason.message : String(reason)))
      .finally(() => !controller.signal.aborted && setLoading(false))
    void loadMcp()
    return () => controller.abort()
  }, [])

  useEffect(() => {
    if (requestedGroup && document?.groups.some((group) => group.name === requestedGroup)) setActiveGroup(requestedGroup)
  }, [document, requestedGroup])

  const fields = useMemo(() => document?.groups.flatMap((group) => group.fields) ?? [], [document])
  const fieldByKey = useMemo(() => new Map(fields.map((field) => [field.key, field])), [fields])

  const changeValue = (field: SettingField, value: string | boolean) => {
    setDraft((current) => ({ ...current, [field.key]: value }))
    setChanged((current) => {
      const next = new Set(current)
      const original = field.kind === 'secret' ? '' : field.value ?? ''
      value === original ? next.delete(field.key) : next.add(field.key)
      return next
    })
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

  const mcpOptions = mcpItems.map((item) => ({
    value: item.name,
    label: item.name,
    description: item.status === 'connected' ? 'Подключён' : item.error || `Статус: ${item.status}`,
  }))
  const visibleGroups = document?.groups.filter((group) => group.name === activeGroup) ?? []

  return (
    <div className="page-stack settings-page">
      <div className="page-title"><div><span className="eyebrow">Server-side configuration</span><h1>Настройки</h1><p>Конфигурация хранится в локальном `.env`; секреты доступны только на запись.</p></div><span className="server-badge"><ShieldCheck size={16} /> Секреты скрыты API</span></div>
      {error && <ErrorBanner message={error} onClose={() => setError('')} />}
      {notice && <div className="alert success"><Check size={17} /><p>{notice}</p></div>}
      <div className="settings-security-note"><KeyRound size={22} /><div><strong>Сохранённые секреты не отправляются в браузер</strong><p>Пустое поле оставляет секрет без изменений. Для удаления используйте «Очистить».</p></div></div>
      <nav className="settings-tabs" aria-label="Разделы настроек">
        {document?.groups.map((group) => <button type="button" className={activeGroup === group.name ? 'active' : ''} key={group.name} onClick={() => { setActiveGroup(group.name); setSearchParams({ section: group.name }, { replace: true }) }}>{group.name}<span>{group.fields.length}</span></button>)}
      </nav>
      {activeGroup === 'OpenCode' && <OpenCodeServerPanel />}
      {activeGroup === 'OpenCode' && <div className="settings-source-status"><span className={`status-dot ${mcpConnected ? 'online' : ''}`} /> <span>{mcpConnected ? `${mcpItems.length} MCP получено от OpenCode` : 'OpenCode не подключён — сохранённые значения останутся доступны'}</span><button type="button" className="icon-button" title="Обновить MCP" disabled={mcpLoading} onClick={() => void loadMcp()}><RefreshCw size={15} className={mcpLoading ? 'spin' : ''} /></button></div>}
      {visibleGroups.map((group) => (
        <section className="configuration-group" key={group.name}>
          <div className="section-heading"><div><h2>{group.name}</h2><span>{group.fields.length} параметров</span></div></div>
          <div className="configuration-grid">
            {group.fields.map((field) => {
              const isCleared = clear.has(field.key)
              const isChanged = changed.has(field.key)
              const inputType = field.kind === 'secret' && !visibleSecrets.has(field.key) ? 'password' : field.kind === 'number' ? 'number' : 'text'
              const inputId = `setting-${field.key}`
              return <div className={`configuration-field ${isCleared ? 'cleared' : ''} ${isChanged ? 'changed' : ''}`} key={field.key}>
                <span className="configuration-label"><label htmlFor={inputId}>{field.label}{field.required && <b>*</b>}</label><span>{isChanged && <small className="changed-badge">изменено</small>}{field.restart_required && <small>restart</small>}</span></span>
                {field.kind === 'boolean'
                  ? <label className="settings-switch" htmlFor={inputId}><input id={inputId} type="checkbox" checked={Boolean(draft[field.key])} onChange={(event) => changeValue(field, event.target.checked)} /><span className="switch" /><span>{Boolean(draft[field.key]) ? 'Включено' : 'Выключено'}</span></label>
                  : field.picker === 'mcp'
                    ? <McpSinglePicker value={String(draft[field.key] ?? '')} options={mcpOptions} onChange={(value) => changeValue(field, value)} />
                    : field.picker === 'mcp_multi'
                      ? <McpMultiPicker value={String(draft[field.key] ?? '')} options={mcpOptions} onChange={(value) => changeValue(field, value)} />
                      : <span className="configuration-input"><input
                    id={inputId}
                    type={inputType}
                    value={String(draft[field.key] ?? '')}
                    min={field.minimum ?? undefined}
                    max={field.maximum ?? undefined}
                    disabled={isCleared}
                    autoComplete="off"
                    placeholder={field.kind === 'secret' && field.configured ? '••••••••  настроено' : field.default || 'Не задано'}
                    onChange={(event) => changeValue(field, event.target.value)}
                  />{field.picker === 'file' || field.picker === 'directory' ? <PathSettingPicker value={String(draft[field.key] ?? '')} mode={field.picker} disabled={isCleared} onChange={(value) => changeValue(field, value)} /> : null}{field.kind === 'secret' && <button type="button" className="button ghost small" onClick={() => setVisibleSecrets((current) => { const next = new Set(current); next.has(field.key) ? next.delete(field.key) : next.add(field.key); return next })}>{visibleSecrets.has(field.key) ? 'Скрыть' : 'Показать'}</button>}{field.kind === 'secret' && field.configured && <button type="button" className={`button small ${isCleared ? 'secondary' : 'danger'}`} onClick={() => toggleClear(field)}>{isCleared ? 'Отменить' : 'Очистить'}</button>}</span>}
                <span className="configuration-meta"><code>{field.key}</code>{field.description && <small>{field.description}</small>}{field.kind === 'secret' && <small className={field.configured && !isCleared ? 'configured' : ''}>{isCleared ? 'Будет удалён' : field.configured ? 'Секрет настроен' : 'Не настроен'}</small>}</span>
              </div>
            })}
          </div>
        </section>
      ))}
      <footer className="settings-actions"><button className="button secondary" disabled={saving || (!changed.size && !clear.size)} onClick={() => document && applyDocument(document)}><X size={16} /> Сбросить правки</button><button className="button primary large" disabled={saving || (!changed.size && !clear.size)} onClick={() => void save()}><Check size={17} /> {saving ? 'Сохраняю…' : 'Сохранить настройки'}</button></footer>
    </div>
  )
}
