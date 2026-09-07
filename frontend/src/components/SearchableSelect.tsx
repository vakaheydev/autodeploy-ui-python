import { useEffect, useMemo, useRef, useState } from 'react'
import { Check, ChevronDown, Search, X } from './Icons'

export interface SelectOption {
  value: string
  label: string
  description?: string
  data?: unknown
}

export function SearchableSelect({
  value,
  options,
  onChange,
  onSearch,
  placeholder = 'Не выбрано',
  searchPlaceholder = 'Поиск…',
  emptyText = 'Ничего не найдено',
  disabled = false,
  loading = false,
  ariaLabel,
  id,
  compact = false,
  clearable = true,
  ariaInvalid = false,
  ariaDescribedBy,
  onOptionContextMenu,
}: {
  value: string
  options: SelectOption[]
  onChange: (value: string) => void
  onSearch?: (query: string) => void
  placeholder?: string
  searchPlaceholder?: string
  emptyText?: string
  disabled?: boolean
  loading?: boolean
  ariaLabel: string
  id?: string
  compact?: boolean
  clearable?: boolean
  ariaInvalid?: boolean
  ariaDescribedBy?: string
  onOptionContextMenu?: (option: SelectOption) => void
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const root = useRef<HTMLDivElement>(null)
  const selected = options.find((option) => option.value === value)
  const visible = useMemo(() => {
    if (onSearch) return options
    const words = query.trim().toLocaleLowerCase('ru').split(/\s+/).filter(Boolean)
    if (!words.length) return options
    return options.filter((option) => {
      const haystack = `${option.label} ${option.value} ${option.description ?? ''}`.toLocaleLowerCase('ru')
      return words.every((word) => haystack.includes(word))
    })
  }, [onSearch, options, query])

  useEffect(() => {
    const close = (event: MouseEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])

  const changeQuery = (next: string) => {
    setQuery(next)
    onSearch?.(next)
  }

  return <div className={`searchable-select ${open ? 'open' : ''} ${compact ? 'compact' : ''}`} ref={root}>
    <button id={id} type="button" className="select-trigger" aria-label={ariaLabel} aria-haspopup="listbox" aria-expanded={open} aria-invalid={ariaInvalid || undefined} aria-describedby={ariaDescribedBy} disabled={disabled} onClick={() => setOpen((current) => !current)}>
      <span className={selected ? '' : 'placeholder'}>{selected?.label ?? (value || placeholder)}</span>
      <ChevronDown size={15} />
    </button>
    {open && <div className="select-popover">
      <label className="select-search"><Search size={15} /><input autoFocus value={query} onChange={(event) => changeQuery(event.target.value)} placeholder={searchPlaceholder} onKeyDown={(event) => event.key === 'Escape' && setOpen(false)} />{query && <button type="button" aria-label="Очистить поиск" onClick={() => changeQuery('')}><X size={13} /></button>}</label>
      <div className="select-options" role="listbox" aria-label={ariaLabel}>
        {clearable && <button type="button" className={!value ? 'selected' : ''} role="option" aria-selected={!value} onClick={() => { onChange(''); setOpen(false) }}><span>{placeholder}</span>{!value && <Check size={14} />}</button>}
        {visible.map((option) => <button type="button" className={option.value === value ? 'selected' : ''} role="option" aria-selected={option.value === value} key={option.value} title={onOptionContextMenu ? 'ПКМ — открыть карточку' : undefined} onContextMenu={(event) => { if (!onOptionContextMenu) return; event.preventDefault(); onOptionContextMenu(option) }} onClick={() => { onChange(option.value); setOpen(false) }}><span><strong>{option.label}</strong>{option.description && <small>{option.description}</small>}</span>{option.value === value && <Check size={14} />}</button>)}
        {!loading && !visible.length && <div className="select-empty">{emptyText}</div>}
        {loading && <div className="select-empty"><span className="typing-dots"><i /><i /><i /></span> Загружаю…</div>}
      </div>
    </div>}
  </div>
}
