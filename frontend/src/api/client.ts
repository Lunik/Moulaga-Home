const API_BASE = '/api'
let profileSessionGeneration = 0

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
    this.name = 'ApiError'
  }
}

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

export function apiDelete<T = void>(path: string): Promise<T> {
  return apiRequest<T>(path, { method: 'DELETE' })
}

export function apiUpload<T>(path: string, body: FormData): Promise<T> {
  return apiRequest<T>(path, { method: 'POST', body })
}

export function advanceProfileSessionGeneration(): void {
  profileSessionGeneration += 1
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
  const requestSessionGeneration = profileSessionGeneration
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
    const isSessionBootstrap = path === '/profiles/session' || path === '/profile-session'
    if (
      response.status === 401
      && !isSessionBootstrap
      && requestSessionGeneration === profileSessionGeneration
      && typeof window !== 'undefined'
    ) {
      advanceProfileSessionGeneration()
      window.dispatchEvent(new Event('moulaga:profile-session-ended'))
    }
    throw new ApiError(message, response.status)
  }

  const changesProfileSession = init.method === 'POST' && (
    path === '/profiles/lock'
    || path === '/profile-session/lock'
    || /^\/profiles\/\d+\/select$/.test(path)
  )
  if (changesProfileSession) advanceProfileSessionGeneration()
  if (init.method && init.method !== 'GET' && typeof window !== 'undefined') {
    window.dispatchEvent(new Event('moulaga:data-mutated'))
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
