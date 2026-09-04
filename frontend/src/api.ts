export class ApiError extends Error {
  status: number
  detail: unknown

  constructor(status: number, message: string, detail?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

function errorMessage(payload: unknown, fallback: string): string {
  if (typeof payload === 'object' && payload !== null) {
    const value = payload as Record<string, unknown>
    if (typeof value.detail === 'string') return value.detail
    if (typeof value.detail === 'object' && value.detail !== null) {
      const detail = value.detail as Record<string, unknown>
      if (typeof detail.message === 'string') return detail.message
    }
    if (typeof value.error === 'object' && value.error !== null) {
      const error = value.error as Record<string, unknown>
      if (typeof error.message === 'string') return error.message
    }
  }
  return fallback
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('accept', 'application/json')
  if (init.body && !headers.has('content-type')) headers.set('content-type', 'application/json')
  const response = await fetch(path, { ...init, headers })
  const contentType = response.headers.get('content-type') ?? ''
  const payload: unknown = contentType.includes('application/json')
    ? await response.json()
    : await response.text()
  if (!response.ok) {
    throw new ApiError(response.status, errorMessage(payload, `HTTP ${response.status}`), payload)
  }
  return payload as T
}

export function post<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  return api<T>(path, { method: 'POST', body: JSON.stringify(body), signal })
}
