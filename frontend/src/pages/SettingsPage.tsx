import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ApiError, api } from '../api'
import { Check, KeyRound, RefreshCw, Search, ShieldCheck, X } from '../components/Icons'
import { ErrorBanner, Spinner } from '../components/Feedback'
import { OpenCodeServerPanel } from '../components/OpenCodeServerPanel'
import { MCPServersPanel } from '../components/MCPServersPanel'
import { SearchableSelect } from '../components/SearchableSelect'
import { McpMultiPicker, McpSinglePicker, PathSettingPicker } from '../components/SettingsPickers'
import { PluginAISettings } from '../components/PluginAISettings'
import { ITSMPromptSettings } from '../components/ITSMPromptSettings'
import type { ITSMPromptSettingsDocument, PluginAIPolicyDocument, SettingField, SettingsDocument } from '../types'

const specialGroups = new Set(['Плагины', 'ITSM и AI'])

interface SettingsSearchItem {
  id: string
  group: string
  label: string
  description: string
  target: string
  searchable: string
}

function normalizedSearch(value: unknown): string {
  return String(value ?? '').toLocaleLowerCase('ru').replace(/ё/g, 'е')
}

function regularSearchItems(document: SettingsDocument | null): SettingsSearchItem[] {
  if (!document) return []
  return document.groups.flatMap((group) => group.fields.map((field) => {
    const details = [field.key, field.description, field.kind, field.picker, field.default, field.value, ...(field.choices ?? [])]
      .filter(Boolean)
      .join(' · ')
    return {
      id: `setting:${field.key}`,
      group: group.name,
      label: field.label,
      description: details,
      target: `setting-${field.key}`,
      searchable: normalizedSearch([group.name, field.label, details].join(' ')),
    }
  }))
}

function auxiliarySearchItems(
  prompts: ITSMPromptSettingsDocument | null,
  plugins: PluginAIPolicyDocument | null,
): SettingsSearchItem[] {
  const items: SettingsSearchItem[] = []
  prompts?.rules.forEach((rule, index) => {
    items.push({
      id: `itsm:${index}:type`,
      group: 'ITSM и AI',
      label: `Ticket Type: ${rule.ticket_type || index + 1}`,
      description: 'Стабильный тип заявки',
      target: `itsm-ticket-type-${index}`,
      searchable: normalizedSearch(`ITSM AI ticket type тип заявки ${rule.ticket_type}`),
    })
    items.push({
      id: `itsm:${index}:prompt`,
      group: 'ITSM и AI',
      label: `Prompt: ${rule.ticket_type || index + 1}`,
      description: rule.prompt,
      target: `itsm-prompt-${index}`,
      searchable: normalizedSearch(`ITSM AI prompt инструкции ${rule.ticket_type} ${rule.prompt}`),
    })
  })
  if (plugins) {
    items.push({
      id: 'plugins:master',
      group: 'Плагины',
      label: 'Доступ Gravitee Copilot к плагинам',
      description: 'Глобальная AI-видимость плагинов',
      target: 'plugin-ai-master-toggle',
      searchable: normalizedSearch('плагины AI Copilot видимость доступ'),
    })
    plugins.plugins.forEach((plugin, pluginIndex) => {
      items.push({
        id: `plugin:${plugin.id}`,
        group: 'Плагины',
        label: plugin.title,
        description: plugin.description || plugin.id,
        target: `plugin-ai-${pluginIndex}-toggle`,
        searchable: normalizedSearch(`плагин ${plugin.title} ${plugin.id} ${plugin.description}`),
      })
      plugin.operations.forEach((operation, operationIndex) => items.push({
        id: `plugin:${plugin.id}:${operation.id}`,
        group: 'Плагины',
        label: `${plugin.title}: ${operation.label}`,
        description: operation.description || operation.tool_name,
        target: `plugin-ai-${pluginIndex}-operation-${operationIndex}`,
        searchable: normalizedSearch(`операция плагина политика разрешение manual approve ${plugin.title} ${plugin.id} ${operation.label} ${operation.id} ${operation.description} ${operation.tool_name}`),
      }))
    })
  }
  return items
}

function draftFrom(document: SettingsDocument): Record<string, string | boolean> {
  return Object.fromEntries(document.groups.flatMap((group) => group.fields.map((field) => [
    field.key,
    field.kind === 'secret' ? '' : field.value ?? '',
  ])))
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function settingFieldErrors(
  reason: unknown,
  fields: SettingField[],
  pendingKeys: string[],
): Record<string, string> {
  if (!(reason instanceof ApiError) || reason.status !== 422) return {}
  const known = new Set(fields.map((field) => field.key))
  const keys = new Set<string>()
  const payload = asRecord(reason.detail)
  const detail = payload?.detail
  const detailRecord = asRecord(detail)
  const declared = detailRecord?.fields
  if (Array.isArray(declared)) {
    declared.forEach((key) => typeof key === 'string' && known.has(key) && keys.add(key))
  }
  if (typeof detailRecord?.field === 'string' && known.has(detailRecord.field)) keys.add(detailRecord.field)

  const validationDetails = Array.isArray(detail)
    ? detail
    : Array.isArray(asRecord(payload?.error)?.details) ? asRecord(payload?.error)?.details as unknown[] : []
  validationDetails.forEach((item) => {
    const loc = asRecord(item)?.loc
    if (Array.isArray(loc)) loc.forEach((part) => typeof part === 'string' && known.has(part) && keys.add(part))
  })

  if (keys.size === 0) {
    const normalizedMessage = reason.message.toLocaleLowerCase()
    fields.forEach((field) => {
      if (normalizedMessage.includes(field.key.toLocaleLowerCase()) || normalizedMessage.includes(field.label.toLocaleLowerCase())) {
        keys.add(field.key)
      }
    })
  }
  const uniquePending = [...new Set(pendingKeys)].filter((key) => known.has(key))
  if (keys.size === 0 && uniquePending.length === 1) keys.add(uniquePending[0])
  return Object.fromEntries([...keys].map((key) => [key, reason.message]))
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
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [notice, setNotice] = useState('')
  const [activeGroup, setActiveGroup] = useState('')
  const [mcpItems, setMcpItems] = useState<Array<{ name: string; status: string; error: string }>>([])
  const [mcpConnected, setMcpConnected] = useState(false)
  const [mcpLoading, setMcpLoading] = useState(false)
  const [globalSearch, setGlobalSearch] = useState('')
  const [promptSearchDocument, setPromptSearchDocument] = useState<ITSMPromptSettingsDocument | null>(null)
  const [pluginSearchDocument, setPluginSearchDocument] = useState<PluginAIPolicyDocument | null>(null)
  const [focusTarget, setFocusTarget] = useState(searchParams.get('field') ?? '')

  const applyDocument = (next: SettingsDocument) => {
    setDocument(next)
    setDraft(draftFrom(next))
    setChanged(new Set())
    setClear(new Set())
    setFieldErrors({})
    setVisibleSecrets(new Set())
    setActiveGroup((current) => {
      if (current && next.groups.some((group) => group.name === current)) return current
      return requestedGroup && (specialGroups.has(requestedGroup) || next.groups.some((group) => group.name === requestedGroup)) ? requestedGroup : next.groups[0]?.name ?? ''
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
    const controller = new AbortController()
    void Promise.all([
      api<ITSMPromptSettingsDocument>('/api/v1/settings/itsm-ai-prompts', { signal: controller.signal }).catch(() => null),
      api<PluginAIPolicyDocument>('/api/v1/plugins/ai-policy', { signal: controller.signal }).catch(() => null),
    ]).then(([prompts, plugins]) => {
      if (controller.signal.aborted) return
      if (prompts && Array.isArray(prompts.rules)) setPromptSearchDocument(prompts)
      if (plugins && Array.isArray(plugins.plugins)) setPluginSearchDocument(plugins)
    })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    if (requestedGroup && (specialGroups.has(requestedGroup) || document?.groups.some((group) => group.name === requestedGroup))) setActiveGroup(requestedGroup)
  }, [document, requestedGroup])

  const fields = useMemo(() => document?.groups.flatMap((group) => group.fields) ?? [], [document])
  const fieldByKey = useMemo(() => new Map(fields.map((field) => [field.key, field])), [fields])
  const searchItems = useMemo(
    () => [...regularSearchItems(document), ...auxiliarySearchItems(promptSearchDocument, pluginSearchDocument)],
    [document, pluginSearchDocument, promptSearchDocument],
  )
  const searchResults = useMemo(() => {
    const words = normalizedSearch(globalSearch).trim().split(/\s+/).filter(Boolean)
    if (!words.length) return []
    return searchItems
      .filter((item) => words.every((word) => item.searchable.includes(word)))
      .sort((left, right) => {
        const query = words.join(' ')
        const leftLabel = normalizedSearch(left.label)
        const rightLabel = normalizedSearch(right.label)
        return Number(rightLabel.startsWith(query)) - Number(leftLabel.startsWith(query))
          || left.label.localeCompare(right.label, 'ru')
      })
      .slice(0, 40)
  }, [globalSearch, searchItems])

  const focusSetting = (target: string) => {
    const attempt = (remaining: number) => {
      const element = window.document.getElementById(target) as HTMLElement | null
      if (!element && remaining > 0) {
        window.setTimeout(() => attempt(remaining - 1), 40)
        return
      }
      if (!element) return
      element.scrollIntoView?.({ behavior: 'smooth', block: 'center' })
      element.focus({ preventScroll: true })
      if (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement) element.select()
    }
    window.setTimeout(() => attempt(15), 0)
  }

  const openSearchResult = (item: SettingsSearchItem) => {
    setActiveGroup(item.group)
    setFocusTarget('')
    window.setTimeout(() => setFocusTarget(item.target), 0)
    setSearchParams({ section: item.group, field: item.target }, { replace: true })
    setGlobalSearch('')
    focusSetting(item.target)
  }

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
    setFieldErrors((current) => {
      if (!current[field.key]) return current
      const next = { ...current }
      delete next[field.key]
      return next
    })
    setError('')
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
    setFieldErrors((current) => {
      if (!current[field.key]) return current
      const next = { ...current }
      delete next[field.key]
      return next
    })
    setError('')
    setNotice('')
  }

  const save = async () => {
    if (!document) return
    setSaving(true); setError(''); setFieldErrors({}); setNotice('')
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
      const inlineErrors = settingFieldErrors(reason, fields, [...changed, ...clear])
      const firstKey = Object.keys(inlineErrors)[0]
      if (firstKey) {
        setFieldErrors(inlineErrors)
        const group = fieldByKey.get(firstKey)?.group
        if (group) {
          setActiveGroup(group)
          setSearchParams({ section: group }, { replace: true })
        }
      } else {
        setError(reason instanceof Error ? reason.message : String(reason))
      }
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
  const hasChanges = changed.size > 0 || clear.size > 0

  return (
    <div className="page-stack settings-page">
      <div className="page-title"><div><span className="eyebrow">Server-side configuration</span><h1>Настройки</h1><p>Конфигурация хранится только на Python-сервере; секреты доступны браузеру исключительно на запись.</p></div><span className="server-badge"><ShieldCheck size={16} /> Секреты скрыты API</span></div>
      {error && <ErrorBanner message={error} onClose={() => setError('')} />}
      {notice && <div className="alert success"><Check size={17} /><p>{notice}</p></div>}
      <div className="settings-security-note"><KeyRound size={22} /><div><strong>Сохранённые секреты не отправляются в браузер</strong><p>Пустое поле оставляет секрет без изменений. Для удаления используйте «Очистить».</p></div></div>
      <section className="settings-global-search">
        <label><Search size={19} /><input className="text-control" aria-label="Поиск по всем настройкам" value={globalSearch} onChange={(event) => setGlobalSearch(event.target.value)} placeholder="Найти любую настройку…" />{globalSearch && <button type="button" className="icon-button" aria-label="Очистить поиск настроек" onClick={() => setGlobalSearch('')}><X size={15} /></button>}</label>
        {globalSearch.trim() && <div className="settings-search-results" role="listbox" aria-label="Найденные настройки">{searchResults.map((item) => <button type="button" role="option" aria-selected="false" key={item.id} onClick={() => openSearchResult(item)}><span><small>{item.group}</small><strong>{item.label}</strong><p>{item.description}</p></span><Search size={15} /></button>)}{searchResults.length === 0 && <div className="settings-search-empty">Ничего не найдено</div>}</div>}
      </section>
      <nav className="settings-tabs" aria-label="Разделы настроек">
        {document?.groups.map((group) => <button type="button" className={activeGroup === group.name ? 'active' : ''} key={group.name} onClick={() => { setActiveGroup(group.name); setFocusTarget(''); setSearchParams({ section: group.name }, { replace: true }) }}>{group.name}<span>{group.fields.length}</span></button>)}
        <button type="button" className={activeGroup === 'ITSM и AI' ? 'active' : ''} onClick={() => { setActiveGroup('ITSM и AI'); setFocusTarget(''); setSearchParams({ section: 'ITSM и AI' }, { replace: true }) }}>ITSM и AI</button>
        <button type="button" className={activeGroup === 'Плагины' ? 'active' : ''} onClick={() => { setActiveGroup('Плагины'); setFocusTarget(''); setSearchParams({ section: 'Плагины' }, { replace: true }) }}>Плагины</button>
      </nav>
      {activeGroup === 'ITSM и AI' && <ITSMPromptSettings focusTarget={focusTarget} onDocumentChange={setPromptSearchDocument} />}
      {activeGroup === 'Плагины' && <PluginAISettings />}
      {activeGroup === 'OpenCode' && <OpenCodeServerPanel />}
      {activeGroup === 'OpenCode' && <MCPServersPanel servers={mcpItems} onRefresh={() => void loadMcp()} />}
      {activeGroup === 'OpenCode' && <div className="settings-source-status"><span className={`status-dot ${mcpConnected ? 'online' : ''}`} /> <span>{mcpConnected ? `${mcpItems.length} MCP получено от OpenCode` : 'OpenCode не подключён — сохранённые значения останутся доступны'}</span><button type="button" className="icon-button" title="Обновить MCP" disabled={mcpLoading} onClick={() => void loadMcp()}><RefreshCw size={15} className={mcpLoading ? 'spin' : ''} /></button></div>}
      {visibleGroups.map((group) => (
        <section className="configuration-group" key={group.name}>
          <div className="section-heading"><div><h2>{group.name}</h2><span>{group.fields.length} параметров</span></div></div>
          <div className="configuration-grid">
            {group.fields.map((field) => {
              const isCleared = clear.has(field.key)
              const isChanged = changed.has(field.key)
              const fieldError = fieldErrors[field.key]
              const inputType = field.kind === 'secret' && !visibleSecrets.has(field.key) ? 'password' : field.kind === 'number' ? 'number' : 'text'
              const inputId = `setting-${field.key}`
              const errorId = `${inputId}-error`
              return <div className={`configuration-field ${isCleared ? 'cleared' : ''} ${isChanged ? 'changed' : ''} ${fieldError ? 'invalid' : ''}`} data-setting-key={field.key} key={field.key}>
                <span className="configuration-label"><label htmlFor={inputId}>{field.label}{field.required && <b>*</b>}</label><span>{isChanged && <small className="changed-badge">изменено</small>}{field.restart_required && <small>restart</small>}</span></span>
                {field.kind === 'boolean'
                  ? <label className="settings-switch" htmlFor={inputId}><input id={inputId} type="checkbox" checked={Boolean(draft[field.key])} aria-invalid={Boolean(fieldError)} aria-describedby={fieldError ? errorId : undefined} onChange={(event) => changeValue(field, event.target.checked)} /><span className="switch" /><span>{Boolean(draft[field.key]) ? 'Включено' : 'Выключено'}</span></label>
                  : field.kind === 'select'
                    ? <SearchableSelect id={inputId} ariaLabel={field.label} clearable={false} value={String(draft[field.key] ?? field.default)} options={(field.choices ?? []).map((choice) => ({ value: choice, label: choice }))} onChange={(value) => changeValue(field, value)} ariaInvalid={Boolean(fieldError)} ariaDescribedBy={fieldError ? errorId : undefined} searchPlaceholder="Найти уровень…" />
                  : field.picker === 'mcp'
                    ? <McpSinglePicker value={String(draft[field.key] ?? '')} options={mcpOptions} onChange={(value) => changeValue(field, value)} />
                    : field.picker === 'mcp_multi'
                      ? <McpMultiPicker value={String(draft[field.key] ?? '')} options={mcpOptions} onChange={(value) => changeValue(field, value)} />
                      : <span className="configuration-input"><input className="text-control"
                    id={inputId}
                    type={inputType}
                    value={String(draft[field.key] ?? '')}
                    min={field.minimum ?? undefined}
                    max={field.maximum ?? undefined}
                    disabled={isCleared}
                    aria-invalid={Boolean(fieldError)}
                    aria-describedby={fieldError ? errorId : undefined}
                    autoComplete="off"
                    placeholder={field.kind === 'secret' && field.configured ? '••••••••  настроено' : field.default || 'Не задано'}
                    onChange={(event) => changeValue(field, event.target.value)}
                  />{field.picker === 'file' || field.picker === 'directory' ? <PathSettingPicker value={String(draft[field.key] ?? '')} mode={field.picker} disabled={isCleared} onChange={(value) => changeValue(field, value)} /> : null}{field.kind === 'secret' && <button type="button" className="button ghost small" onClick={() => setVisibleSecrets((current) => { const next = new Set(current); next.has(field.key) ? next.delete(field.key) : next.add(field.key); return next })}>{visibleSecrets.has(field.key) ? 'Скрыть' : 'Показать'}</button>}{field.kind === 'secret' && field.configured && <button type="button" className={`button small ${isCleared ? 'secondary' : 'danger'}`} onClick={() => toggleClear(field)}>{isCleared ? 'Отменить' : 'Очистить'}</button>}</span>}
                {fieldError && <span className="configuration-error" id={errorId} role="alert"><X size={13} />{fieldError}</span>}
                <span className="configuration-meta"><code>{field.key}</code>{field.description && <small>{field.description}</small>}{field.kind === 'secret' && <small className={field.configured && !isCleared ? 'configured' : ''}>{isCleared ? 'Будет удалён' : field.configured ? 'Секрет настроен' : 'Не настроен'}</small>}</span>
              </div>
            })}
          </div>
        </section>
      ))}
      {hasChanges && <footer className="settings-actions"><button className="button secondary" disabled={saving} onClick={() => document && applyDocument(document)}><X size={16} /> Сбросить правки</button><button className="button primary large" disabled={saving} onClick={() => void save()}><Check size={17} /> {saving ? 'Сохраняю…' : 'Сохранить настройки'}</button></footer>}
    </div>
  )
}
