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

export interface ReferenceDependencyDescriptor {
  field: string
  parameter: string
  item_field: string | null
}

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
  plural_contract?: {
    first_instance_path: string
    additional_instance_path_template: string
    additional_instance_number_starts_at: number
    draft_array_supported: boolean
  }
  depends_on: string | null
  depends_on_field: string | null
  reference_dependencies?: ReferenceDependencyDescriptor[]
  reference?: ReferenceDescriptor
  options?: ReferenceItem[]
  fields?: FieldDocument[]
  instances?: Record<string, FieldDocument[]>
}

export interface FormSummary {
  id: string
  title: string
  category: string
  category_label: string
  description?: string
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
  custom_actions: Array<{ id: string; label: string; available: boolean; reason: string; style: string; confirmation_required: boolean; dialog?: boolean }>
}

export interface ActionDialogButtonDocument {
  id: string
  label: string
  style: string
  confirmation_required: boolean
  requires_valid_dialog: boolean
  close_on_success: boolean
}

export interface ActionDialogDocument {
  success: boolean
  id: string
  title: string
  description: string
  form_version: string
  values: Record<string, unknown>
  fields: FieldDocument[]
  actions: ActionDialogButtonDocument[]
  message?: string
  validation_scope?: 'form' | 'dialog'
  validation?: ValidationResult
  form_values?: Record<string, unknown>
  data?: unknown
  close_dialog?: boolean
  confirmation_required?: boolean
  confirmation_text?: string
  confirmation_token?: string
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

export interface ITSMPromptRule {
  ticket_type: string
  prompt: string
}

export interface ITSMPromptSettingsDocument {
  rules: ITSMPromptRule[]
  warning: string
  max_rules: number
  max_ticket_type_chars: number
  max_prompt_chars: number
  precedence: 'ui_override_then_corporate_hook'
}

export type TicketTone = 'default' | 'info' | 'success' | 'warning' | 'danger'

export interface TicketFilterOption {
  value: string
  label: string
}

export interface TicketFilterDefinition {
  key: string
  label: string
  kind: 'text' | 'select' | 'multiselect' | 'date' | 'boolean'
  options: TicketFilterOption[]
  placeholder: string
  default: unknown
}

export interface TicketSortDefinition {
  key: string
  label: string
}

export interface TicketListConfiguration {
  enabled: boolean
  description: string
  filters: TicketFilterDefinition[]
  sorts: TicketSortDefinition[]
  default_sort: string
  default_direction: 'asc' | 'desc'
  page_size: number
  empty_title: string
  empty_text: string
}

export interface TicketAttribute {
  key: string
  label: string
  value: unknown
  kind: 'text' | 'multiline' | 'code' | 'datetime' | 'badge' | 'json'
  url: string
  copyable: boolean
  tone: TicketTone
}

export interface TicketListItem {
  id: string
  title: string
  subtitle: string
  status: string
  status_tone: TicketTone
  updated_at: string
  attributes: TicketAttribute[]
}

export interface TicketListDocument {
  items: TicketListItem[]
  total: number
  offset: number
  limit: number
  has_more: boolean
}

export interface TicketSection {
  id: string
  title: string
  attributes: TicketAttribute[]
}

export interface TicketActionDocument {
  id: string
  label: string
  description: string
  style: 'primary' | 'secondary' | 'success' | 'danger' | 'warning'
  color: string
  confirmation_required: boolean
  disabled_reason: string
}

export interface TicketCardDocument {
  id: string
  title: string
  subtitle: string
  description: string
  status: string
  status_tone: TicketTone
  updated_at: string
  environment: string
  version: string
  sections: TicketSection[]
  actions: TicketActionDocument[]
}

export interface TicketActionResponse {
  success: boolean
  message?: string
  card?: TicketCardDocument
  data?: unknown
  confirmation_required?: boolean
  confirmation_text?: string
  confirmation_token?: string
}

export interface PluginSummary {
  id: string
  title: string
  description: string
  category: string
  icon: string
  keywords: string[]
  operation_count: number
}

export interface PluginOperationDocument {
  id: string
  label: string
  description: string
  style: 'primary' | 'secondary' | 'success' | 'danger' | string
  confirmation_required: boolean
  requires_valid_fields: boolean
}

export interface PluginChartSeries {
  name: string
  values: number[]
  color: string
}

export type PluginWidget =
  | { id: string; kind: 'text'; title?: string; text: string; tone?: string }
  | { id: string; kind: 'metric'; label: string; value: unknown; detail?: string; tone?: string }
  | { id: string; kind: 'image'; title?: string; src: string; alt: string; caption?: string }
  | { id: string; kind: 'chart'; title?: string; chart_type: 'line' | 'area' | 'bar' | 'pie' | 'doughnut'; labels: string[]; series: PluginChartSeries[]; y_label?: string }
  | { id: string; kind: 'table'; title?: string; columns: string[]; rows: unknown[][] }

export interface PluginDocument {
  id: string
  title: string
  description: string
  category: string
  icon: string
  version: string
  fields: FieldDocument[]
  initial_values: Record<string, unknown>
  operations: PluginOperationDocument[]
  widgets: PluginWidget[]
}

export interface PluginActionResponse {
  success: boolean
  message: string
  values?: Record<string, unknown>
  fields?: FieldDocument[]
  widgets?: PluginWidget[]
  data?: unknown
  validation?: ValidationResult
  confirmation_required?: boolean
  confirmation_text?: string
  confirmation_token?: string
}

export type PluginAIOperationPolicy = 'deny' | 'allow' | 'manual'

export interface PluginAIPolicyDocument {
  ai_visible: boolean
  requires_new_session: boolean
  plugins: Array<{
    id: string
    title: string
    description: string
    visible: boolean
    operations: Array<{
      id: string
      label: string
      description: string
      policy: PluginAIOperationPolicy
      tool_name: string
    }>
  }>
}
