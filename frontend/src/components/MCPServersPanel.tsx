import { useState } from 'react'
import { api, post } from '../api'
import { RefreshCw, ServerCog as Server, Code2 as Wrench } from './Icons'

interface MCPServer { name: string; status: string; error: string }
interface MCPTool { name: string; description: string; policy: 'deny' | 'ask' | 'allow' }

function ServerCard({ server, onRefresh }: { server: MCPServer; onRefresh: () => void }) {
  const [tools, setTools] = useState<MCPTool[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const base = `/api/v1/opencode/mcp/${encodeURIComponent(server.name)}`
  const load = async (refresh = false) => {
    setBusy(true); setError('')
    try {
      const result = await api<{ tools: MCPTool[] }>(`${base}/tools?refresh=${refresh}`)
      setTools(result.tools)
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { setBusy(false) }
  }
  const restart = async () => {
    setBusy(true); setError(''); setNotice('')
    try {
      await post(`${base}/restart`, {})
      setNotice('Перезапуск выполнен')
      if (tools) await load(true)
      onRefresh()
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { setBusy(false) }
  }
  const policy = async (tool: MCPTool, value: MCPTool['policy']) => {
    setBusy(true); setError(''); setNotice('')
    try {
      const result = await post<{ applies: string }>(`${base}/tools/${encodeURIComponent(tool.name)}/policy`, { policy: value })
      setTools(current => current?.map(item => item.name === tool.name ? { ...item, policy: value } : item) ?? null)
      setNotice(result.applies === 'new_session' ? 'Сохранено. Для сброса прежних постоянных разрешений OpenCode v1 создайте новый чат.' : 'Сохранено. Применится перед следующим запросом Copilot.')
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { setBusy(false) }
  }
  const status = ({ connected: 'Подключён', pending: 'Подключается', disabled: 'Отключён', failed: 'Ошибка', needs_auth: 'Нужен вход' } as Record<string, string>)[server.status] || server.status
  return <article className="mcp-server-card" aria-label={`MCP ${server.name}`}>
    <header><div><Server size={18} /><strong>{server.name}</strong><span className={`mcp-status ${server.status}`}>{status}</span></div>
      <button type="button" className="button secondary small" disabled={busy} onClick={() => void restart()}><RefreshCw size={14} /> Перезапустить</button>
    </header>
    {server.error && <p className="mcp-error">{server.error}</p>}
    <details onToggle={event => { if (event.currentTarget.open && tools === null && !busy) void load() }}>
      <summary><Wrench size={15} /> Инструменты и разрешения {tools && <span>{tools.length}</span>}</summary>
      <p className="mcp-policy-hint">Правила сохраняются автоматически. Серверы для Copilot выбираются в поле «Разрешённые MCP».</p>
      <button type="button" className="button ghost small" disabled={busy} onClick={() => void load(true)}><RefreshCw size={13} /> Обновить инструменты</button>
      {busy && <p role="status">Применяем изменения…</p>}
      {tools?.length === 0 && <p>Сервер не вернул инструментов.</p>}
      <div className="mcp-tool-list">{tools?.map(tool => <div className="mcp-tool-row" key={tool.name}>
        <div><code>{tool.name}</code><p>{tool.description}</p></div>
        <select aria-label={`Разрешение ${server.name} / ${tool.name}`} value={tool.policy} disabled={busy}
          onChange={event => void policy(tool, event.target.value as MCPTool['policy'])}>
          <option value="deny">Запретить</option><option value="ask">Всегда спрашивать</option><option value="allow">Разрешить</option>
        </select>
      </div>)}</div>
    </details>
    {error && <p className="mcp-error" role="alert">{error}</p>}
    {notice && <p role="status" className="mcp-notice">{notice}</p>}
  </article>
}

export function MCPServersPanel({ servers, onRefresh }: { servers: MCPServer[]; onRefresh: () => void }) {
  return <section className="mcp-servers-panel" aria-label="Серверы MCP">
    {servers.map(server => <ServerCard key={server.name} server={server} onRefresh={onRefresh} />)}
  </section>
}
