import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import { ArrowLeft, Check, ChevronDown, File, Folder, Search, Upload, X } from './Icons'
import { Modal } from './Feedback'
import type { SelectOption } from './SearchableSelect'
import { SearchableSelect } from './SearchableSelect'

interface FilesystemEntry { name: string; path: string; is_dir: boolean; is_file: boolean }
interface FilesystemDocument { current: string; parent: string; roots: string[]; entries: FilesystemEntry[] }

export function PathSettingPicker({
  value, mode, disabled, onChange,
}: {
  value: string
  mode: 'file' | 'directory'
  disabled?: boolean
  onChange: (value: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [document, setDocument] = useState<FilesystemDocument | null>(null)
  const [query, setQuery] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const load = async (path = '') => {
    setLoading(true); setError('')
    try {
      setDocument(await api<FilesystemDocument>(`/api/v1/settings/filesystem?path=${encodeURIComponent(path)}`))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setLoading(false)
    }
  }
  const show = () => { setOpen(true); setQuery(''); void load(value) }
  const visible = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase('ru')
    return (document?.entries ?? []).filter((item) => {
      if (mode === 'directory' && !item.is_dir) return false
      return !needle || item.name.toLocaleLowerCase('ru').includes(needle)
    })
  }, [document, mode, query])

  return <>
    <button type="button" className="button secondary small" disabled={disabled} onClick={show}><Upload size={15} /> Обзор</button>
    {open && <Modal
      title={mode === 'directory' ? 'Выберите папку' : 'Выберите файл'}
      onClose={() => setOpen(false)}
      footer={<>
        <button type="button" className="button secondary" onClick={() => setOpen(false)}>Отмена</button>
        {mode === 'directory' && <button type="button" className="button primary" disabled={!document} onClick={() => { if (document) onChange(document.current); setOpen(false) }}><Check size={16} /> Выбрать эту папку</button>}
      </>}
    >
      <div className="path-picker">
        <div className="path-picker-nav">
          <button type="button" className="icon-button" disabled={!document?.parent || loading} title="На уровень выше" onClick={() => void load(document?.parent)}><ArrowLeft size={17} /></button>
          <code>{document?.current || 'Загрузка…'}</code>
        </div>
        {(document?.roots.length ?? 0) > 1 && <div className="path-roots">{document?.roots.map((root) => <button type="button" className="button ghost small" key={root} onClick={() => void load(root)}>{root}</button>)}</div>}
        <label className="path-search"><Search size={16} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Найти в текущей папке…" />{query && <button type="button" className="icon-button" onClick={() => setQuery('')}><X size={14} /></button>}</label>
        {error && <div className="alert error">{error}</div>}
        <div className="path-entries" aria-busy={loading}>
          {visible.map((item) => <button
            type="button"
            key={item.path}
            onClick={() => {
              if (item.is_dir) void load(item.path)
              else { onChange(item.path); setOpen(false) }
            }}
          >
            {item.is_dir ? <Folder size={18} /> : <File size={18} />}
            <span>{item.name}</span>
            {item.is_dir && <ChevronDown className="rotate-left" size={15} />}
          </button>)}
          {!loading && !visible.length && <span className="muted option-empty">Подходящих элементов нет</span>}
          {loading && <span className="muted option-empty">Открываю папку…</span>}
        </div>
      </div>
    </Modal>}
  </>
}

export function McpSinglePicker({ value, options, onChange }: { value: string; options: SelectOption[]; onChange: (value: string) => void }) {
  const completeOptions = value && !options.some((item) => item.value === value)
    ? [{ value, label: value, description: 'Сохранён в настройках, сейчас не обнаружен' }, ...options]
    : options
  return <SearchableSelect value={value} options={completeOptions} onChange={onChange} ariaLabel="JSON Repository MCP" placeholder="MCP не выбран" searchPlaceholder="Найти MCP…" />
}

export function McpMultiPicker({ value, options, onChange }: { value: string; options: SelectOption[]; onChange: (value: string) => void }) {
  const root = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const selected = useMemo(() => value.split(',').map((item) => item.trim()).filter(Boolean), [value])
  const selectedSet = useMemo(() => new Set(selected), [selected])
  const completeOptions = useMemo(() => {
    const missing = selected.filter((name) => !options.some((item) => item.value === name)).map((name) => ({ value: name, label: name, description: 'Сохранён, сейчас не обнаружен' }))
    return [...missing, ...options]
  }, [options, selected])
  const visible = completeOptions.filter((item) => `${item.label} ${item.description ?? ''}`.toLocaleLowerCase('ru').includes(query.trim().toLocaleLowerCase('ru')))

  useEffect(() => {
    const close = (event: MouseEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])
  const toggle = (name: string) => {
    const next = new Set(selectedSet)
    next.has(name) ? next.delete(name) : next.add(name)
    onChange([...next].join(','))
  }

  return <div className={`mcp-multi-picker ${open ? 'open' : ''}`} ref={root}>
    <button type="button" className="select-trigger" aria-haspopup="listbox" aria-expanded={open} onClick={() => setOpen((current) => !current)}><span>{selected.length ? `Выбрано MCP: ${selected.length}` : 'MCP не выбраны'}</span><ChevronDown size={15} /></button>
    {open && <div className="select-popover">
      <label className="select-search"><Search size={15} /><input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Найти MCP…" /></label>
      <div className="select-options mcp-options" role="listbox" aria-label="Разрешённые MCP">
        {visible.map((item) => <button type="button" className={selectedSet.has(item.value) ? 'selected' : ''} key={item.value} onClick={() => toggle(item.value)}><span><strong>{item.label}</strong>{item.description && <small>{item.description}</small>}</span>{selectedSet.has(item.value) && <Check size={14} />}</button>)}
        {!visible.length && <div className="select-empty">MCP не найдены</div>}
      </div>
    </div>}
    {selected.length > 0 && <div className="mcp-chips">{selected.map((name) => <button type="button" key={name} onClick={() => toggle(name)}>{name}<X size={12} /></button>)}</div>}
  </div>
}
