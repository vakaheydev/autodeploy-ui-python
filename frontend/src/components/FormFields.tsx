import { ChangeEvent, useEffect, useMemo, useRef, useState } from 'react'
import { post } from '../api'
import { Check, FileJson, Plus, RefreshCw, Search, Trash2, Upload, X } from './Icons'
import type { FieldDocument, ReferenceItem, ValidationError } from '../types'
import { SearchableSelect } from './SearchableSelect'
import { ReferenceDetailsModal } from './ReferenceDetailsModal'

interface FieldProps {
  field: FieldDocument
  value: unknown
  values: Record<string, unknown>
  environment: string
  formId: string
  errors: ValidationError[]
  disabled?: boolean
  onChange: (value: unknown) => void
  onObjectChange?: (key: string, value: unknown) => void
  onObjectDelete?: (key: string) => void
  onFieldChange?: (path: string) => void
  review?: Record<string, { confidence: string; proposedValue: unknown; source?: string | null; reason?: string | null; conflict?: string | null }>
  onReview?: (key: string, accept: boolean) => void
}

interface OptionsResponse {
  items: ReferenceItem[]
  total: number
  has_more: boolean
}

function errorsForField(field: FieldDocument, errors: ValidationError[]) {
  return errors.filter((item) => item.field === field.path || item.field === field.key)
}

function fieldErrorId(field: FieldDocument) {
  return `field-error-${field.path.replace(/[^a-zA-Z0-9_-]+/g, '-')}`
}

function FieldError({ field, errors }: { field: FieldDocument; errors: ValidationError[] }) {
  const relevant = errorsForField(field, errors)
  return relevant.length ? <div className="field-errors" id={fieldErrorId(field)} role="alert">{relevant.map((item) => <span key={`${item.field}-${item.code}-${item.message}`}><X size={13} />{item.message}</span>)}</div> : null
}

function referenceSearchPlaceholder(searchKeys: string[]) {
  return searchKeys.length > 1
    ? `Можно искать по: ${searchKeys.join(', ')}`
    : 'Фильтр значений…'
}

function ReferenceField(props: FieldProps) {
  const { field, values, environment, formId, disabled, onChange } = props
  const reference = field.reference!
  const invalid = errorsForField(field, props.errors).length > 0
  const errorId = invalid ? fieldErrorId(field) : undefined
  const [items, setItems] = useState<ReferenceItem[]>(field.options ?? [])
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [total, setTotal] = useState(field.options?.length ?? 0)
  const [detailItem, setDetailItem] = useState<ReferenceItem | null>(null)
  const requestSequence = useRef(0)
  const itemCache = useRef(new Map<string, ReferenceItem>())
  const dependency = field.depends_on ? values[field.depends_on] : undefined
  const serverBacked = field.options === undefined

  const load = async (refresh = false, requestedQuery = query) => {
    const sequence = ++requestSequence.current
    setLoading(true)
    setLoadError('')
    try {
      const result = await post<OptionsResponse>(reference.endpoint, {
        environment,
        values,
        query: requestedQuery,
        offset: 0,
        limit: 500,
        refresh,
      })
      if (sequence !== requestSequence.current) return
      setItems(result.items)
      setTotal(result.total)
    } catch (error) {
      if (sequence !== requestSequence.current) return
      setLoadError(error instanceof Error ? error.message : String(error))
      setItems([])
    } finally {
      if (sequence === requestSequence.current) setLoading(false)
    }
  }

  useEffect(() => {
    // Invalidate a request started for the previous field/environment before
    // changing to inline data or an unavailable dependency.
    requestSequence.current += 1
    itemCache.current.clear()
    if (field.options !== undefined) {
      setItems(field.options)
      setTotal(field.options.length)
      setLoading(false)
      setLoadError('')
      return
    }
    if (field.depends_on && (dependency === undefined || dependency === null || dependency === '')) {
      setItems([])
      setTotal(0)
      setLoading(false)
      return
    }
  }, [field.options, field.depends_on, dependency, environment, reference.endpoint])

  useEffect(() => {
    if (!serverBacked) return
    if (field.depends_on && (dependency === undefined || dependency === null || dependency === '')) return
    const timer = window.setTimeout(() => void load(false, query), 260)
    return () => window.clearTimeout(timer)
  }, [query, serverBacked, field.depends_on, environment, reference.endpoint, dependency])

  const searchable = items.length > 8 || serverBacked
  const shown = useMemo(() => {
    if (serverBacked) return items
    const needle = query.trim().toLocaleLowerCase('ru')
    if (!needle) return items
    return items.filter((item) => reference.search_keys.some((key) => String(item[key] ?? '').toLocaleLowerCase('ru').includes(needle)))
  }, [items, query, reference.search_keys, serverBacked])
  const label = (item: ReferenceItem) => String(item[reference.label_key] ?? item[reference.value_key] ?? '')
  const identifier = (item: ReferenceItem) => String(item[reference.value_key] ?? '')
  const searchableDetails = (item: ReferenceItem) => reference.search_keys
    .filter((key) => key !== reference.label_key)
    .map((key) => {
      const value = String(item[key] ?? '').trim()
      return value ? `${key}: ${value}` : ''
    })
    .filter(Boolean)
    .join(' · ')
  const searchPlaceholder = referenceSearchPlaceholder(reference.search_keys)
  useEffect(() => {
    items.forEach((item) => itemCache.current.set(String(item[reference.value_key] ?? ''), item))
  }, [items, reference.value_key])
  const selectedIds = new Set(field.type === 'select'
    ? (props.value === undefined || props.value === null || props.value === '' ? [] : [String(props.value)])
    : (Array.isArray(props.value) ? props.value.map(String) : []))
  const shownById = new Map(shown.map((item) => [identifier(item), item]))
  const pinned = [...selectedIds].map((id) => shownById.get(id) ?? itemCache.current.get(id)).filter((item): item is ReferenceItem => Boolean(item))
  const ordered = [...pinned, ...shown.filter((item) => !selectedIds.has(identifier(item)))]

  const openDetails = (item: ReferenceItem) => {
    setDetailItem(item)
  }
  const details = detailItem && <ReferenceDetailsModal item={detailItem} title={label(detailItem)} onClose={() => setDetailItem(null)} />

  if (field.type === 'select') {
    return (
      <div className="reference-control">
        <div className="reference-select-row">
          <SearchableSelect
            id={field.path}
            ariaLabel={field.label}
            value={String(props.value ?? '')}
            disabled={disabled}
            loading={loading}
            options={ordered.map((item) => ({ value: identifier(item), label: label(item), description: searchableDetails(item), data: item }))}
            onChange={onChange}
            onSearch={searchable ? setQuery : undefined}
            onOptionContextMenu={(option) => openDetails(option.data as ReferenceItem)}
            searchPlaceholder={searchPlaceholder}
            ariaInvalid={invalid}
            ariaDescribedBy={errorId}
          />
          {reference.source === 'http' && <button type="button" className="icon-button reference-refresh" disabled={loading || disabled} onClick={() => void load(true)} title="Обновить справочник"><RefreshCw size={16} className={loading ? 'spin' : ''} /></button>}
        </div>
        {loading && <small className="muted">Загружаю справочник…</small>}
        {!loading && serverBacked && total > items.length && <small className="muted">Показано {items.length} из {total}. Уточните поиск.</small>}
        {loadError && <small className="field-load-error">{loadError}</small>}
        {details}
      </div>
    )
  }

  const selected = selectedIds
  const toggle = (id: string) => {
    const next = new Set(selected)
    next.has(id) ? next.delete(id) : next.add(id)
    onChange([...next])
  }
  return (
    <div className="reference-control multiselect">
      <div className="reference-toolbar">
        <label className="mini-search"><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={searchPlaceholder} /></label>
        {reference.source === 'http' && <button type="button" className="icon-button" disabled={loading || disabled} onClick={() => void load(true)} title="Обновить справочник"><RefreshCw size={16} className={loading ? 'spin' : ''} /></button>}
      </div>
      <div className="option-list" role="group" aria-label={field.label} aria-invalid={invalid || undefined} aria-describedby={errorId}>
        {ordered.map((item) => {
          const id = identifier(item)
          const detailsText = searchableDetails(item)
          return <label className={`option-row ${selected.has(id) ? 'selected' : ''}`} key={id} title="ПКМ — открыть карточку" onContextMenu={(event) => { event.preventDefault(); openDetails(item) }}><input type="checkbox" aria-label={label(item)} checked={selected.has(id)} disabled={disabled} onChange={() => toggle(id)} /><span className="option-copy"><strong>{label(item)}</strong>{detailsText && <small>{detailsText}</small>}</span>{selected.has(id) && <Check className="option-selected-mark" size={15} />}</label>
        })}
        {!loading && shown.length === 0 && <span className="muted option-empty">Значения не найдены</span>}
      </div>
      <small className="selection-count">Выбрано: {selected.size}</small>
      {!loading && serverBacked && total > items.length && <small className="muted">Показано {items.length} из {total}. Уточните поиск.</small>}
      {loadError && <small className="field-load-error">{loadError}</small>}
      {details}
    </div>
  )
}

function BasicField(props: FieldProps) {
  const { field, value, disabled, onChange } = props
  const invalid = errorsForField(field, props.errors).length > 0
  const errorId = invalid ? fieldErrorId(field) : undefined
  const commit = (next: unknown) => {
    onChange(next)
    props.onFieldChange?.(field.path)
  }
  if (field.reference) return <ReferenceField {...props} onChange={commit} />
  if (field.type === 'textarea') {
    return <textarea id={field.path} rows={5} value={String(value ?? '')} disabled={disabled} aria-invalid={invalid || undefined} aria-describedby={errorId} placeholder={field.placeholder} onChange={(event) => commit(event.target.value)} />
  }
  if (field.type === 'checkbox') {
    return <label className="switch-control"><input id={field.path} type="checkbox" checked={Boolean(value)} disabled={disabled} aria-invalid={invalid || undefined} aria-describedby={errorId} onChange={(event) => commit(event.target.checked)} /><span className="switch" /><span>{Boolean(value) ? 'Включено' : 'Выключено'}</span></label>
  }
  if (field.type === 'number') {
    return <input id={field.path} type="number" value={value === null || value === undefined ? '' : String(value)} disabled={disabled} aria-invalid={invalid || undefined} aria-describedby={errorId} placeholder={field.placeholder} onChange={(event) => commit(event.target.value === '' ? null : Number(event.target.value))} />
  }
  if (field.type === 'file') {
    const readFile = (event: ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0]
      if (!file) return
      const reader = new FileReader()
      reader.onload = () => commit(String(reader.result ?? ''))
      reader.readAsText(file)
    }
    return <div className="file-control"><label className="button secondary"><Upload size={16} /> Выбрать файл<input type="file" accept={field.file_type || undefined} disabled={disabled} onChange={readFile} hidden /></label><textarea id={field.path} rows={7} value={String(value ?? '')} disabled={disabled} aria-invalid={invalid || undefined} aria-describedby={errorId} placeholder={field.placeholder || 'Содержимое файла'} onChange={(event) => commit(event.target.value)} /></div>
  }
  return <input id={field.path} type="text" value={String(value ?? '')} disabled={disabled} aria-invalid={invalid || undefined} aria-describedby={errorId} placeholder={field.placeholder} onChange={(event) => commit(event.target.value)} />
}

function SingleField(props: FieldProps) {
  const { field, value, errors, onChange } = props
  const reviewKey = props.review?.[field.path] ? field.path : field.key
  const fieldReview = props.review?.[reviewKey]
  const invalid = errorsForField(field, errors).length > 0
  if (!field.visible) return null
  if (field.type === 'block') {
    const block = typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {}
    return (
      <fieldset className={`block-field ${invalid ? 'invalid' : ''}`} data-form-field-path={field.path} data-form-field-key={field.key}>
        <legend><FileJson size={17} /> {field.label}{field.required && <b>*</b>}</legend>
        {field.hint && <p className="field-hint">{field.hint}</p>}
        <div className="block-fields">
          {(field.fields ?? []).map((nested) => {
            const nestedField = { ...nested, path: `${field.path}.${nested.key}` }
            return (
            <PluralField
              key={nested.key}
              {...props}
              field={nestedField}
              values={block}
              value={block[nested.key]}
              onChange={(nestedValue) => onChange({ ...block, [nested.key]: nestedValue })}
              onObjectChange={(key, nestedValue) => onChange({ ...block, [key]: nestedValue })}
              onObjectDelete={(key) => {
                const next = { ...block }
                delete next[key]
                onChange(next)
              }}
            />
            )
          })}
        </div>
        <FieldError field={field} errors={errors} />
      </fieldset>
    )
  }
  return (
    <div className={`form-field ${invalid ? 'invalid' : ''} ${fieldReview ? `ai-review confidence-${fieldReview.confidence}` : ''}`} data-form-field-path={field.path} data-form-field-key={field.key}>
      <div className="field-label-row"><label className="field-label" htmlFor={field.path}>{field.label}{field.required && <b>*</b>}</label>{fieldReview && <div className="field-review-controls"><span className="confidence-badge" title={[fieldReview.source, fieldReview.reason, fieldReview.conflict].filter(Boolean).join('\n')}>{fieldReview.confidence}</span><button type="button" className="review-accept" aria-label={`Принять ${field.label}`} onClick={() => props.onReview?.(reviewKey, true)}>✓</button><button type="button" className="review-reject" aria-label={`Отклонить ${field.label}`} onClick={() => props.onReview?.(reviewKey, false)}>×</button></div>}</div>
      {field.hint && <p className="field-hint">{field.hint}</p>}
      <BasicField {...props} />
      <FieldError field={field} errors={errors} />
    </div>
  )
}

export function PluralField(props: FieldProps) {
  const { field, values, onChange } = props
  if (!field.plural) return <SingleField {...props} />
  const instances = Object.keys(values)
    .filter((key) => key === field.key || new RegExp(`^${field.key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}_\\d+$`).test(key))
    .sort((left, right) => {
      const index = (value: string) => value === field.key ? 1 : Number(value.slice(field.key.length + 1))
      return index(left) - index(right)
    })
  if (!instances.includes(field.key)) instances.unshift(field.key)
  const add = () => {
    if (field.plural_max && instances.length >= field.plural_max) return
    let nextIndex = 2
    while (Object.prototype.hasOwnProperty.call(values, `${field.key}_${nextIndex}`)) nextIndex += 1
    const key = `${field.key}_${nextIndex}`
    props.onObjectChange?.(key, field.default ?? '')
    props.onFieldChange?.(field.path.replace(/[^.]+$/, key))
  }
  const addLabel = field.type === 'block' && field.label
    ? `Добавить ${field.label.charAt(0).toLocaleLowerCase('ru')}${field.label.slice(1)}`
    : 'Добавить значение'
  return (
    <div className="plural-group">
      {instances.map((key, index) => (
        <div className="plural-instance" key={key}>
          <SingleField {...props} field={{ ...field, key, path: field.path.replace(/[^.]+$/, key), label: index ? `${field.label} · ${index + 1}` : field.label, plural: false }} value={values[key]} onChange={(next) => props.onObjectChange ? props.onObjectChange(key, next) : index === 0 && onChange(next)} />
          {index > 0 && props.onObjectDelete && <button type="button" className="icon-button danger floating-remove" onClick={() => { props.onObjectDelete?.(key); props.onFieldChange?.(field.path.replace(/[^.]+$/, key)) }} aria-label="Удалить значение"><Trash2 size={16} /></button>}
        </div>
      ))}
      <button type="button" className="button ghost small" onClick={add} disabled={Boolean(field.plural_max && instances.length >= field.plural_max)}><Plus size={15} /> {addLabel}</button>
    </div>
  )
}

export function FormFields({ fields, values, environment, formId, errors, disabled, onValuesChange, onFieldChange, review, onReview }: {
  fields: FieldDocument[]
  values: Record<string, unknown>
  environment: string
  formId: string
  errors: ValidationError[]
  disabled?: boolean
  onValuesChange: (values: Record<string, unknown>) => void
  onFieldChange?: (path: string) => void
  review?: FieldProps['review']
  onReview?: FieldProps['onReview']
}) {
  const change = (key: string, value: unknown) => onValuesChange({ ...values, [key]: value })
  const remove = (key: string) => {
    const next = { ...values }
    delete next[key]
    onValuesChange(next)
  }
  return <div className="fields-grid">{fields.map((field) => (
    <PluralField
      key={field.key}
      field={field}
      value={values[field.key]}
      values={values}
      environment={environment}
      formId={formId}
      errors={errors}
      disabled={disabled}
      onChange={(value) => change(field.key, value)}
      onObjectChange={change}
      onObjectDelete={remove}
      onFieldChange={onFieldChange}
      review={review}
      onReview={onReview}
    />
  ))}</div>
}
