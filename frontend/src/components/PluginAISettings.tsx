import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { Check, Puzzle, ShieldCheck, X } from './Icons'
import { ErrorBanner, Spinner } from './Feedback'
import { SearchableSelect } from './SearchableSelect'
import type { PluginAIPolicyDocument, PluginAIOperationPolicy } from '../types'

const policyOptions = [
  { value: 'deny', label: 'Запретить', description: 'Операция не публикуется для AI.' },
  { value: 'manual', label: 'Manual approve', description: 'OpenCode спросит подтверждение перед каждым вызовом.' },
  { value: 'allow', label: 'Разрешить', description: 'AI может вызвать операцию без отдельного вопроса.' },
]

function editable(document: PluginAIPolicyDocument) {
  return {
    ai_visible: document.ai_visible,
    plugins: document.plugins.map((plugin) => ({
      id: plugin.id,
      visible: plugin.visible,
      operations: Object.fromEntries(plugin.operations.map((operation) => [operation.id, operation.policy])),
    })),
  }
}

export function PluginAISettings() {
  const [document, setDocument] = useState<PluginAIPolicyDocument | null>(null)
  const [draft, setDraft] = useState<ReturnType<typeof editable> | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const apply = (next: PluginAIPolicyDocument) => {
    setDocument(next)
    setDraft(editable(next))
  }
  useEffect(() => {
    const controller = new AbortController()
    api<PluginAIPolicyDocument>('/api/v1/plugins/ai-policy', { signal: controller.signal })
      .then(apply)
      .catch((reason: unknown) => !controller.signal.aborted && setError(reason instanceof Error ? reason.message : String(reason)))
      .finally(() => !controller.signal.aborted && setLoading(false))
    return () => controller.abort()
  }, [])
  const changed = useMemo(() => Boolean(document && draft && JSON.stringify(editable(document)) !== JSON.stringify(draft)), [document, draft])

  const setPluginVisible = (id: string, visible: boolean) => setDraft((current) => current ? ({ ...current, plugins: current.plugins.map((plugin) => plugin.id === id ? { ...plugin, visible } : plugin) }) : current)
  const setOperation = (pluginId: string, operationId: string, policy: PluginAIOperationPolicy) => setDraft((current) => current ? ({ ...current, plugins: current.plugins.map((plugin) => plugin.id === pluginId ? { ...plugin, operations: { ...plugin.operations, [operationId]: policy } } : plugin) }) : current)
  const save = async () => {
    if (!draft) return
    setSaving(true); setError(''); setNotice('')
    try {
      const next = await api<PluginAIPolicyDocument>('/api/v1/plugins/ai-policy', { method: 'PUT', body: JSON.stringify(draft) })
      apply(next)
      setNotice('Политика сохранена. Создайте новый AI-чат, чтобы OpenCode получил обновлённые инструменты и разрешения.')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <Spinner label="Загружаю политику плагинов…" />
  if (!document || !draft) return error ? <ErrorBanner message={error} /> : null

  return <section className="plugin-ai-settings">
    {error && <ErrorBanner message={error} onClose={() => setError('')} />}
    {notice && <div className="alert success"><Check size={17} /><p>{notice}</p></div>}
    <div className={`plugin-ai-master ${draft.ai_visible !== document.ai_visible ? 'changed' : ''}`}>
      <span className="plugin-policy-icon"><ShieldCheck size={22} /></span>
      <div><h2>Доступ Gravitee Copilot</h2><p>Глобально публиковать AI каталог корпоративных плагинов и разрешённые операции.</p></div>
      <label className="settings-switch"><input aria-label="ИИ видит плагины" type="checkbox" checked={draft.ai_visible} onChange={(event) => setDraft({ ...draft, ai_visible: event.target.checked })} /><span className="switch" /><span>{draft.ai_visible ? 'Включено' : 'Выключено'}</span></label>
    </div>
    <div className="settings-security-note"><Puzzle size={22} /><div><strong>Политика закрыта по умолчанию</strong><p>Плагин должен быть видимым, а каждая операция — явно разрешённой. `Manual approve` вызывает стандартный запрос разрешения OpenCode. Также должен быть включён встроенный MCP Server.</p></div></div>
    {document.plugins.length === 0 && <div className="empty-state"><span className="empty-orb" /><h3>Корпоративные плагины не зарегистрированы</h3><p>Подключите `AUTODEPLOY_PLUGIN_REGISTRAR` и перезапустите сервер.</p></div>}
    <div className="plugin-policy-list">{document.plugins.map((plugin) => {
      const current = draft.plugins.find((item) => item.id === plugin.id)!
      const original = editable(document).plugins.find((item) => item.id === plugin.id)!
      const pluginChanged = JSON.stringify(current) !== JSON.stringify(original)
      return <article className={`plugin-policy-card ${pluginChanged ? 'changed' : ''}`} key={plugin.id}>
        <header><span className="plugin-card-icon"><Puzzle size={18} /></span><div><h3>{plugin.title}</h3>{plugin.description && <p>{plugin.description}</p>}<code>{plugin.id}</code></div><label className="settings-switch"><input aria-label={`ИИ видит плагин ${plugin.title}`} type="checkbox" checked={current.visible} onChange={(event) => setPluginVisible(plugin.id, event.target.checked)} /><span className="switch" /><span>{current.visible ? 'Виден AI' : 'Скрыт от AI'}</span></label></header>
        {plugin.operations.length > 0 && <div className="plugin-operation-policies">{plugin.operations.map((operation) => <div className={current.operations[operation.id] !== original.operations[operation.id] ? 'changed' : ''} key={operation.id}><div><strong>{operation.label}</strong>{operation.description && <p>{operation.description}</p>}<code>{operation.tool_name}</code></div><SearchableSelect ariaLabel={`Политика ${operation.label}`} compact clearable={false} value={current.operations[operation.id]} options={policyOptions} onChange={(value) => setOperation(plugin.id, operation.id, value as PluginAIOperationPolicy)} /></div>)}</div>}
        {plugin.operations.length === 0 && <p className="muted plugin-no-operations">У плагина нет операций: AI сможет только прочитать его публичное описание и состояние.</p>}
      </article>
    })}</div>
    {changed && <footer className="settings-actions"><button className="button secondary" disabled={saving} onClick={() => apply(document)}><X size={16} /> Сбросить правки</button><button className="button primary large" disabled={saving} onClick={() => void save()}><Check size={17} /> {saving ? 'Сохраняю…' : 'Сохранить AI-политику'}</button></footer>}
  </section>
}
