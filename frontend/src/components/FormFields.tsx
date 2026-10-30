import { ChangeEvent, memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { post } from '../api'
import { Check, FileJson, LoaderCircle, Plus, RefreshCw, Search, Trash2, Upload, X } from './Icons'
import type { FieldDocument, ReferenceItem, ValidationError } from '../types'
import { SearchableSelect } from './SearchableSelect'
import { ReferenceDetailsModal } from './ReferenceDetailsModal'
import { Modal } from './Feedback'

interface ReviewEntry {
  confidence: string
  proposedValue: unknown
  source?: string | null
  reason?: string | null
  conflict?: string | null
}

interface FieldProps {
  field: FieldDocument
  value: unknown
  values: Record<string, unknown>
  rootValues: Record<string, unknown>
  environment: string
  formId: string
  errors: ValidationError[]
  disabled?: boolean
  onChange: (value: unknown) => void
  onObjectChange?: (key: string, value: unknown) => void
  onObjectDelete?: (key: string) => void
  onFieldChange?: (path: string) => void
  onFieldAction?: (path: string, action: NonNullable<FieldDocument['actions']>[number]) => void
  review?: Record<string, ReviewEntry>
  onReview?: (key: string, accept: boolean) => void
  dialogContext?: {
    ownerFieldPath?: string
    formValues: Record<string, unknown>
    formVersion: string
  }
}

interface OptionsResponse {
  items: ReferenceItem[]
  total: number
  has_more: boolean
  updated_at?: number | null
}

interface ReferenceCacheStatusResponse {
  environment: string
  updated_at: number | null
}

const REFERENCE_PAGE_SIZE = 100
const fieldSignatureCache = new WeakMap<FieldDocument, string>()

function fieldSignature(field: FieldDocument) {
  const cached = fieldSignatureCache.get(field)
  if (cached !== undefined) return cached
  const value = JSON.stringify(field)
  fieldSignatureCache.set(field, value)
  return value
}

function pathBelongsToField(path: string | null, field: FieldDocument) {
  if (!path) return false
  if (path === field.path || path.startsWith(`${field.path}.`)) return true
  if (!field.plural) return false
  const escaped = field.path.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return new RegExp(`^${escaped}_\\d+(?:\\.|$)`).test(path)
}

function fieldErrorsSignature(field: FieldDocument, errors: ValidationError[]) {
  return JSON.stringify(errors.filter((item) => pathBelongsToField(item.field, field)))
}

function fieldReviewSignature(field: FieldDocument, review: FieldProps['review']) {
  return JSON.stringify(Object.entries(review ?? {}).filter(([path]) => pathBelongsToField(path, field)))
}

function dependencySignatureForProps(props: FieldProps) {
  const dependencies = props.field.reference_dependencies ?? []
  const values = dependencies.map((dependency) => [
    dependency.scope ?? 'current',
    dependency.field,
    dependency.scope === 'form'
      ? props.dialogContext?.formValues[dependency.field]
      : props.values[dependency.field],
  ])
  if (props.field.depends_on) values.push([
    'current',
    props.field.depends_on,
    props.values[props.field.depends_on],
  ])
  const visitFormDependencies = (field: FieldDocument) => {
    for (const dependency of field.reference_dependencies ?? []) {
      if (dependency.scope === 'form') values.push([
        'form',
        dependency.field,
        props.dialogContext?.formValues[dependency.field],
      ])
    }
    for (const nested of field.fields ?? []) visitFormDependencies(nested)
    for (const instance of Object.values(field.instances ?? {})) {
      for (const nested of instance) visitFormDependencies(nested)
    }
  }
  if (props.field.type === 'block') visitFormDependencies(props.field)
  return JSON.stringify(values)
}

function pluralValuesSignature(field: FieldDocument, values: Record<string, unknown>) {
  if (!field.plural) return ''
  const prefix = `${field.key}_`
  return JSON.stringify(Object.entries(values).filter(([key]) => key === field.key || key.startsWith(prefix)))
}

function sameFieldProps(previous: FieldProps, next: FieldProps) {
  return previous.formId === next.formId
    && previous.environment === next.environment
    && previous.disabled === next.disabled
    && Boolean(previous.onFieldAction) === Boolean(next.onFieldAction)
    && Object.is(previous.value, next.value)
    && fieldSignature(previous.field) === fieldSignature(next.field)
    && pluralValuesSignature(previous.field, previous.values) === pluralValuesSignature(next.field, next.values)
    && dependencySignatureForProps(previous) === dependencySignatureForProps(next)
    && fieldErrorsSignature(previous.field, previous.errors) === fieldErrorsSignature(next.field, next.errors)
    && fieldReviewSignature(previous.field, previous.review) === fieldReviewSignature(next.field, next.review)
    && previous.dialogContext?.formVersion === next.dialogContext?.formVersion
    && previous.dialogContext?.ownerFieldPath === next.dialogContext?.ownerFieldPath
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

function stringControlValue(value: unknown) {
  return typeof value === 'string' || typeof value === 'number'
    ? String(value)
    : ''
}

function emptyDependency(value: unknown) {
  if (value === null || value === undefined || value === '') return true
  if (Array.isArray(value)) return value.length === 0
  return typeof value === 'object' && Object.keys(value as object).length === 0
}

function formatReferenceUpdatedAt(value: number | null) {
  if (value === null) return 'Справочник ещё не обновлялся'
  return new Intl.DateTimeFormat('ru-RU', {
    dateStyle: 'long',
    timeStyle: 'medium',
  }).format(new Date(value * 1000))
}

function ReferenceField(props: FieldProps) {
  const { field, values, rootValues, environment, disabled, onChange } = props
  const reference = field.reference!
  const invalid = errorsForField(field, props.errors).length > 0
  const errorId = invalid ? fieldErrorId(field) : undefined
  const [items, setItems] = useState<ReferenceItem[]>(field.options ?? [])
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [total, setTotal] = useState(field.options?.length ?? 0)
  const [detailItem, setDetailItem] = useState<ReferenceItem | null>(null)
  const [refreshDialogOpen, setRefreshDialogOpen] = useState(false)
  const [refreshStatusLoading, setRefreshStatusLoading] = useState(false)
  const [refreshStatusError, setRefreshStatusError] = useState('')
  const [updatedAt, setUpdatedAt] = useState<number | null>(null)
  const requestSequence = useRef(0)
  const requestController = useRef<AbortController | null>(null)
  const itemCache = useRef(new Map<string, ReferenceItem>())
  const explicitDependencies = field.reference_dependencies ?? []
  const dependencyValue = (dependency: typeof explicitDependencies[number]) => (
    dependency.scope === 'form'
      ? props.dialogContext?.formValues[dependency.field]
      : values[dependency.field]
  )
  const dependencyValues = new Map(explicitDependencies.map((item) => [
    item.parameter || item.field,
    dependencyValue(item),
  ]))
  const legacyDependency = field.depends_on ? values[field.depends_on] : undefined
  const dependencySignature = JSON.stringify([
    field.depends_on ? [field.depends_on, legacyDependency] : null,
    ...explicitDependencies.map((item) => [
      item.scope ?? 'current',
      item.field,
      dependencyValue(item),
    ]),
  ])
  const dependencyBlocked = Boolean(
    (field.depends_on && emptyDependency(legacyDependency))
    || explicitDependencies.length > 0 && reference.required_params.some(
      (parameter) => emptyDependency(dependencyValues.get(parameter)),
    ),
  )
  const serverBacked = field.options === undefined
  const selectedValue = stringControlValue(props.value)
  const selectedValues = field.type === 'select'
    ? (selectedValue ? [selectedValue] : [])
    : (Array.isArray(props.value) ? props.value.map(String) : [])
  const selectedIds = new Set(selectedValues)
  // Draft values arrive after the initial form document.  A server-backed
  // catalog may already have loaded its first page without those IDs, so use a
  // stable selection signature to request the selected records once they are
  // restored (manual and AI drafts share this path).
  const selectionSignature = JSON.stringify(selectedValues)

  const referenceRequest = (extra: Record<string, unknown>) => props.dialogContext ? {
    environment,
    form_values: props.dialogContext.formValues,
    dialog_values: rootValues,
    form_version: props.dialogContext.formVersion,
    ...(props.dialogContext.ownerFieldPath ? { owner_field_path: props.dialogContext.ownerFieldPath } : {}),
    ...extra,
  } : {
    environment,
    values: rootValues,
    ...extra,
  }

  const load = async (refresh = false, requestedQuery = query) => {
    const sequence = ++requestSequence.current
    requestController.current?.abort()
    const controller = new AbortController()
    requestController.current = controller
    setLoading(true)
    setLoadError('')
    try {
      const result = await post<OptionsResponse>(reference.endpoint, referenceRequest({
        query: requestedQuery,
        offset: 0,
        limit: REFERENCE_PAGE_SIZE,
        refresh,
      }), controller.signal)
      if (sequence !== requestSequence.current) return
      setItems(result.items)
      setTotal(result.total)
      if (result.updated_at !== undefined) setUpdatedAt(result.updated_at)
    } catch (error) {
      if (sequence !== requestSequence.current) return
      if (error instanceof Error && error.name === 'AbortError') return
      setLoadError(error instanceof Error ? error.message : String(error))
      setItems([])
    } finally {
      if (sequence === requestSequence.current) {
        if (requestController.current === controller) requestController.current = null
        setLoading(false)
      }
    }
  }

  const openRefreshDialog = async () => {
    setRefreshDialogOpen(true)
    setRefreshStatusLoading(true)
    setRefreshStatusError('')
    try {
      const result = await post<ReferenceCacheStatusResponse>(reference.endpoint, referenceRequest({
        query: '',
        offset: 0,
        limit: 1,
        refresh: false,
        cache_status_only: true,
      }))
      setUpdatedAt(result.updated_at)
    } catch (error) {
      setRefreshStatusError(error instanceof Error ? error.message : String(error))
    } finally {
      setRefreshStatusLoading(false)
    }
  }

  const confirmRefresh = () => {
    setRefreshDialogOpen(false)
    void load(true, query)
  }

  useEffect(() => {
    // Invalidate a request started for the previous field/environment before
    // changing to inline data or an unavailable dependency.
    requestSequence.current += 1
    requestController.current?.abort()
    requestController.current = null
    itemCache.current.clear()
    setUpdatedAt(null)
    if (field.options !== undefined) {
      setItems(field.options)
      setTotal(field.options.length)
      setLoading(false)
      setLoadError('')
      return
    }
    if (dependencyBlocked) {
      setItems([])
      setTotal(0)
      setLoading(false)
      return
    }
  }, [field.options, dependencyBlocked, dependencySignature, environment, reference.endpoint])

  useEffect(() => () => requestController.current?.abort(), [])

  useEffect(() => {
    if (!serverBacked) return
    if (dependencyBlocked) return
    const timer = window.setTimeout(() => void load(false, query), 260)
    return () => window.clearTimeout(timer)
  }, [query, serverBacked, dependencyBlocked, dependencySignature, environment, reference.endpoint, selectionSignature])

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
  const shownById = new Map(shown.map((item) => [identifier(item), item]))
  const pinned = [...selectedIds].map((id) => shownById.get(id) ?? itemCache.current.get(id)).filter((item): item is ReferenceItem => Boolean(item))
  const ordered = [...pinned, ...shown.filter((item) => !selectedIds.has(identifier(item)))]

  const openDetails = (item: ReferenceItem) => {
    setDetailItem(item)
  }
  const details = detailItem && <ReferenceDetailsModal item={detailItem} title={label(detailItem)} onClose={() => setDetailItem(null)} />
  const refreshConfirmation = refreshDialogOpen && <Modal
    title="Обновление справочника"
    onClose={() => setRefreshDialogOpen(false)}
    footer={<>
      <button type="button" className="button secondary" onClick={() => setRefreshDialogOpen(false)}>Отмена</button>
      <button type="button" className="button primary" disabled={refreshStatusLoading || loading || dependencyBlocked} onClick={confirmRefresh}><RefreshCw size={16} /> Обновить</button>
    </>}
  >
    <div className="reference-refresh-dialog">
      <p>Заново загрузить данные справочника <strong>«{field.label}»</strong>?</p>
      <dl className="reference-refresh-meta">
        <div><dt>Окружение</dt><dd>{environment.replaceAll('_', ' ').toUpperCase()}</dd></div>
        <div><dt>Последнее обновление</dt><dd>{refreshStatusLoading ? <span className="reference-refresh-loading"><LoaderCircle className="spin" size={15} /> Проверяю…</span> : formatReferenceUpdatedAt(updatedAt)}</dd></div>
      </dl>
      {refreshStatusError && <div className="alert error" role="alert">{refreshStatusError}</div>}
    </div>
  </Modal>

  if (field.type === 'select') {
    return (
      <div className="reference-control">
        <div className="reference-select-row">
          <SearchableSelect
            id={field.path}
            ariaLabel={field.label}
            value={selectedValue}
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
          <button type="button" className="icon-button reference-refresh" disabled={loading || disabled || dependencyBlocked} onClick={() => void openRefreshDialog()} title="Обновить справочник" aria-label={`Обновить справочник «${field.label}»`}><RefreshCw size={16} className={loading ? 'spin' : ''} /></button>
        </div>
        {loading && <small className="muted">Загружаю справочник…</small>}
        {!loading && serverBacked && total > items.length && <small className="muted">Показано {items.length} из {total}. Уточните поиск.</small>}
        {loadError && <small className="field-load-error">{loadError}</small>}
        {details}
        {refreshConfirmation}
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
        <button type="button" className="icon-button reference-refresh" disabled={loading || disabled || dependencyBlocked} onClick={() => void openRefreshDialog()} title="Обновить справочник" aria-label={`Обновить справочник «${field.label}»`}><RefreshCw size={16} className={loading ? 'spin' : ''} /></button>
      </div>
      <div className="option-list" role="group" aria-label={field.label} aria-invalid={invalid || undefined} aria-describedby={errorId}>
        {ordered.map((item) => {
          const id = identifier(item)
          const detailsText = searchableDetails(item)
          return <label className={`option-row ${selected.has(id) ? 'selected' : ''}`} key={id} title="ПКМ — открыть карточку" onContextMenu={(event) => { event.preventDefault(); openDetails(item) }}><input className="option-checkbox" type="checkbox" aria-label={label(item)} checked={selected.has(id)} disabled={disabled} onChange={() => toggle(id)} /><span className="option-copy"><strong>{label(item)}</strong>{detailsText && <small>{detailsText}</small>}</span>{selected.has(id) && <Check className="option-selected-mark" size={15} />}</label>
        })}
        {!loading && shown.length === 0 && <span className="muted option-empty">Значения не найдены</span>}
      </div>
      <small className="selection-count">Выбрано: {selected.size}</small>
      {!loading && serverBacked && total > items.length && <small className="muted">Показано {items.length} из {total}. Уточните поиск.</small>}
      {loadError && <small className="field-load-error">{loadError}</small>}
      {details}
      {refreshConfirmation}
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
    return <textarea className="text-control" id={field.path} rows={5} value={stringControlValue(value)} disabled={disabled} aria-invalid={invalid || undefined} aria-describedby={errorId} placeholder={field.placeholder} onChange={(event) => commit(event.target.value)} />
  }
  if (field.type === 'checkbox') {
    return <label className="switch-control"><input id={field.path} type="checkbox" checked={Boolean(value)} disabled={disabled} aria-invalid={invalid || undefined} aria-describedby={errorId} onChange={(event) => commit(event.target.checked)} /><span className="switch" /><span>{Boolean(value) ? 'Включено' : 'Выключено'}</span></label>
  }
  if (field.type === 'number') {
    return <input className="text-control" id={field.path} type="number" value={value === null || value === undefined ? '' : String(value)} disabled={disabled} aria-invalid={invalid || undefined} aria-describedby={errorId} placeholder={field.placeholder} onChange={(event) => commit(event.target.value === '' ? null : Number(event.target.value))} />
  }
  if (field.type === 'file') {
    const readFile = (event: ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0]
      if (!file) return
      const reader = new FileReader()
      reader.onload = () => commit(String(reader.result ?? ''))
      reader.readAsText(file)
    }
    return <div className="file-control"><label className="button secondary"><Upload size={16} /> Выбрать файл<input type="file" accept={field.file_type || undefined} disabled={disabled} onChange={readFile} hidden /></label><textarea className="text-control" id={field.path} rows={7} value={stringControlValue(value)} disabled={disabled} aria-invalid={invalid || undefined} aria-describedby={errorId} placeholder={field.placeholder || 'Содержимое файла'} onChange={(event) => commit(event.target.value)} /></div>
  }
  return <input className="text-control" id={field.path} type="text" value={stringControlValue(value)} disabled={disabled} aria-invalid={invalid || undefined} aria-describedby={errorId} placeholder={field.placeholder} onChange={(event) => commit(event.target.value)} />
}

function ReviewControls({ fieldLabel, reviewKey, review, onReview }: {
  fieldLabel: string
  reviewKey: string
  review: ReviewEntry
  onReview?: FieldProps['onReview']
}) {
  return (
    <div className="field-review-controls">
      <span className="confidence-badge" title={[review.source, review.reason, review.conflict].filter(Boolean).join('\n')}>{review.confidence}</span>
      <button type="button" className="review-accept" aria-label={`Принять ${fieldLabel}`} onClick={() => onReview?.(reviewKey, true)}>✓</button>
      <button type="button" className="review-reject" aria-label={`Отклонить ${fieldLabel}`} onClick={() => onReview?.(reviewKey, false)}>×</button>
    </div>
  )
}

function SingleField(props: FieldProps) {
  const { field, value, errors, onChange } = props
  // Review decisions are path-addressed. Falling back to a leaf key for a
  // nested field could accidentally attach a top-level proposal with the same
  // name to every repeated block instance.
  const reviewKey = props.review?.[field.path]
    ? field.path
    : field.path === field.key && props.review?.[field.key]
      ? field.key
      : ''
  const fieldReview = reviewKey ? props.review?.[reviewKey] : undefined
  const invalid = errorsForField(field, errors).length > 0
  if (!field.visible) return null
  if (field.type === 'block') {
    const block = typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {}
    return (
      <fieldset className={`block-field ${invalid ? 'invalid' : ''} ${fieldReview ? `ai-review confidence-${fieldReview.confidence}` : ''}`} data-form-field-path={field.path} data-form-field-key={field.key}>
        <legend><span className="block-legend-label"><FileJson size={17} /> {field.label}{field.required && <b>*</b>}</span>{fieldReview && <ReviewControls fieldLabel={field.label} reviewKey={reviewKey} review={fieldReview} onReview={props.onReview} />}</legend>
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
        <FieldActionButtons {...props} />
        <FieldError field={field} errors={errors} />
      </fieldset>
    )
  }
  return (
    <div className={`form-field ${invalid ? 'invalid' : ''} ${fieldReview ? `ai-review confidence-${fieldReview.confidence}` : ''}`} data-form-field-path={field.path} data-form-field-key={field.key}>
      <div className="field-label-row"><label className="field-label" htmlFor={field.path}>{field.label}{field.required && <b>*</b>}</label>{fieldReview && <ReviewControls fieldLabel={field.label} reviewKey={reviewKey} review={fieldReview} onReview={props.onReview} />}</div>
      {field.hint && <p className="field-hint">{field.hint}</p>}
      <BasicField {...props} />
      <FieldActionButtons {...props} />
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
          <SingleField {...props} field={{ ...field, key, path: field.path.replace(/[^.]+$/, key), label: index ? `${field.label} · ${index + 1}` : field.label, plural: false, fields: key === field.key ? field.fields : field.instances?.[key] ?? field.fields }} value={values[key]} onChange={(next) => props.onObjectChange ? props.onObjectChange(key, next) : index === 0 && onChange(next)} />
          {index > 0 && props.onObjectDelete && <button type="button" className="icon-button danger floating-remove" onClick={() => { props.onObjectDelete?.(key); props.onFieldChange?.(field.path.replace(/[^.]+$/, key)) }} aria-label="Удалить значение"><Trash2 size={16} /></button>}
        </div>
      ))}
      <button type="button" className="button ghost small" onClick={add} disabled={Boolean(field.plural_max && instances.length >= field.plural_max)}><Plus size={15} /> {addLabel}</button>
    </div>
  )
}

function FieldActionButtons({ field, disabled, onFieldAction }: FieldProps) {
  if (!field.actions?.length) return null
  return <div className="field-actions" role="group" aria-label={`Действия поля ${field.label}`}>
    {field.actions.map(action => <button key={action.id} type="button"
      className={`button ${['primary', 'secondary', 'success', 'danger'].includes(action.style.toLowerCase()) ? action.style.toLowerCase() : 'secondary'} small`}
      disabled={disabled || !onFieldAction} onClick={() => onFieldAction?.(field.path, action)}>
      {action.label}
    </button>)}
  </div>
}

const MemoizedPluralField = memo(PluralField, sameFieldProps)

export function FormFields({ fields, values, environment, formId, errors, disabled, onValuesChange, onFieldChange, onFieldAction, review, onReview, dialogContext }: {
  fields: FieldDocument[]
  values: Record<string, unknown>
  environment: string
  formId: string
  errors: ValidationError[]
  disabled?: boolean
  onValuesChange: (values: Record<string, unknown>) => void
  onFieldChange?: (path: string) => void
  onFieldAction?: FieldProps['onFieldAction']
  review?: FieldProps['review']
  onReview?: FieldProps['onReview']
  dialogContext?: FieldProps['dialogContext']
}) {
  const valuesRef = useRef(values)
  const callbacksRef = useRef({ onValuesChange, onFieldChange, onFieldAction, onReview })
  valuesRef.current = values
  callbacksRef.current = { onValuesChange, onFieldChange, onFieldAction, onReview }
  const change = useCallback((key: string, value: unknown) => {
    callbacksRef.current.onValuesChange({ ...valuesRef.current, [key]: value })
  }, [])
  const remove = useCallback((key: string) => {
    const next = { ...valuesRef.current }
    delete next[key]
    callbacksRef.current.onValuesChange(next)
  }, [])
  const fieldChanged = useCallback((path: string) => callbacksRef.current.onFieldChange?.(path), [])
  const fieldAction = useCallback<NonNullable<FieldProps['onFieldAction']>>((path, action) => callbacksRef.current.onFieldAction?.(path, action), [])
  const reviewField = useCallback((key: string, accept: boolean) => callbacksRef.current.onReview?.(key, accept), [])
  return <div className="fields-grid">{fields.map((field) => (
    <MemoizedPluralField
      key={field.key}
      field={field}
      value={values[field.key]}
      values={values}
      rootValues={values}
      environment={environment}
      formId={formId}
      errors={errors}
      disabled={disabled}
      onChange={(value) => change(field.key, value)}
      onObjectChange={change}
      onObjectDelete={remove}
      onFieldChange={fieldChanged}
      onFieldAction={onFieldAction ? fieldAction : undefined}
      review={review}
      onReview={reviewField}
      dialogContext={dialogContext}
    />
  ))}</div>
}
