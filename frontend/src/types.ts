export type FieldType =
  | 'text'
  | 'textarea'
  | 'select'
  | 'multiselect'
  | 'checkbox'
  | 'number'
  | 'file'
  | 'block'

export interface Environment {
  key: string
  label: string
}

export interface ReferenceDescriptor {
  source: 'local' | 'http' | string
  resource: string
  value_key: string
  label_key: string
  search_keys: string[]
  detail_keys: string[]
  required_params: string[]
  endpoint: string
}

export type ReferenceItem = Record<string, unknown>

export interface FieldDocument {
  key: string
  path: string
  label: string
  type: FieldType
  required: boolean
  visible: boolean
  dynamic: boolean
  placeholder: string
  default: unknown
  hint: string
  file_type: string
  width: number
  plural: boolean
  plural_max: number | null
  depends_on: string | null
  depends_on_field: string | null
  reference?: ReferenceDescriptor
  options?: ReferenceItem[]
  fields?: FieldDocument[]
}

export interface FormSummary {
  id: string
  title: string
  category: string
  category_label: string
  version: string
  field_count: number
  confirm_submit: boolean
  itsm_support: boolean
  keywords?: string[]
}

export interface Category {
  id: string
  label: string
  forms: FormSummary[]
}

export interface FormDocument {
  id: string
  title: string
  category: string
  category_label: string
  version: string
  confirm_submit: boolean
  itsm_support: boolean
  http_method: string
  fields: FieldDocument[]
  initial_values: Record<string, unknown>
  custom_actions: Array<{ id: string; label: string; available: boolean; reason: string; style: string; confirmation_required: boolean }>
}

export interface ValidationError {
  field: string | null
  code: string
  message: string
}

export interface ValidationResult {
  valid: boolean
  values: Record<string, unknown>
  errors: ValidationError[]
  visible_fields: string[]
}

export interface PreviewResult extends ValidationResult {
  method?: string
  endpoint?: string
  payload?: unknown
  confirmation_required?: boolean
  confirmation_text?: string
  confirmation_token?: string
}

export interface SubmitResult {
  success: true
  message: string
  submission_id: string
  status: 'pending' | 'success' | 'waiting' | 'error'
  title: string
  content: string
  response: unknown
  payload: unknown
  polling: boolean
  poll_interval_ms: number | null
}

export interface RunRecord {
  run_id: string
  form_id: string
  environment: string
  timestamp: number
  form_data: Record<string, unknown>
  fields_snapshot: Record<string, string>
  stale: boolean
}

export interface FormDraftSummary {
  id: string
  form_id: string
  title: string
  environment: string
  form_version: string
  revision: number
  source: 'ai' | 'manual' | string
  created_at: number
  updated_at: number
  valid: boolean
  stale: boolean
  review_count: number
}

export interface SettingField {
  key: string
  label: string
  group: string
  kind: 'text' | 'secret' | 'number' | 'boolean' | 'path'
  picker?: '' | 'file' | 'directory' | 'mcp' | 'mcp_multi'
  default: string
  description: string
  required: boolean
  restart_required: boolean
  minimum: number | null
  maximum: number | null
  configured: boolean
  value: string | boolean | null
}

export interface SettingsDocument {
  groups: Array<{ name: string; fields: SettingField[] }>
  saved_keys?: string[]
  restart_required?: boolean
  reconnect_opencode?: boolean
}
