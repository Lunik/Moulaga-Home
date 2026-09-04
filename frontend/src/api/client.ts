const API_BASE = '/api'

export function apiGet<T>(path: string): Promise<T> {
  return apiRequest<T>(path)
}

export function apiPost<T>(path: string, body?: unknown): Promise<T> {
  return apiRequest<T>(path, { method: 'POST', body: jsonBody(body) })
}

export function apiPatch<T>(path: string, body: unknown): Promise<T> {
  return apiRequest<T>(path, { method: 'PATCH', body: jsonBody(body) })
}

export function apiPut<T>(path: string, body: unknown): Promise<T> {
  return apiRequest<T>(path, { method: 'PUT', body: jsonBody(body) })
}

export function apiDelete(path: string): Promise<void> {
  return apiRequest<void>(path, { method: 'DELETE' })
}

export function apiUpload<T>(path: string, body: FormData): Promise<T> {
  return apiRequest<T>(path, { method: 'POST', body })
}

export function queryString(values: Record<string, string | number | boolean | null | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value))
  }
  const result = search.toString()
  return result ? `?${result}` : ''
}

async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body !== undefined && !(init.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers })
  const text = await response.text()

  if (!response.ok) {
    let message = `La requête a échoué (${response.status})`
    if (text) {
      try {
        const payload: unknown = JSON.parse(text)
        if (
          typeof payload === 'object'
          && payload !== null
          && 'detail' in payload
          && typeof payload.detail === 'string'
        ) {
          message = payload.detail
        }
      } catch (error) {
        throw new Error(message, { cause: error })
      }
    }
    throw new Error(message)
  }

  if (!text) return undefined as T
  try {
    return JSON.parse(text) as T
  } catch (error) {
    throw new Error('La réponse du serveur est invalide.', { cause: error })
  }
}

function jsonBody(body: unknown): string | undefined {
  return body === undefined ? undefined : JSON.stringify(body)
}
