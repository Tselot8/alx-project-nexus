export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly fieldErrors: Readonly<Record<string, readonly string[]>> = {},
  ) { super(message); this.name = 'ApiError' }
}
export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
export function apiPath(path: string): string {
  const origin = globalThis.location.origin
  const url = new URL(path, origin)
  const resource = path.split('?')[0] || ''
  if (!path.startsWith('/api/v2/') || resource.includes('\\') || /%2f|%5c|%2e/i.test(resource)
    || url.origin !== origin || !url.pathname.startsWith('/api/v2/')
    || url.hash || url.username || url.password) {
    throw new ApiError(0, 'unsafe_request', 'This request is not allowed.')
  }
  for (const key of url.searchParams.keys()) {
    if (/token|secret|password|share/i.test(key)) {
      throw new ApiError(0, 'unsafe_request', 'Credentials cannot be sent in URLs.')
    }
  }
  return url.pathname + url.search
}
function responseError(status: number, data: unknown): ApiError {
  const envelope = isRecord(data) && isRecord(data.error) ? data.error : {}
  const details = isRecord(envelope.details) ? envelope.details : {}
  const fields: Record<string, string[]> = {}
  for (const [key, value] of Object.entries(details)) {
    if (/^[a-z_]{1,50}$/.test(key) && Array.isArray(value)) {
      fields[key] = value.filter((item): item is string => typeof item === 'string')
        .map(item => item.slice(0, 500))
    }
  }
  const fallback = status === 401 ? 'Your session has expired. Please sign in again.'
    : status === 403 ? 'You do not have access to this action.'
    : status === 404 ? 'This resource is unavailable.'
    : status === 429 ? 'Too many requests. Please wait before trying again.'
    : status >= 500 ? 'The service is temporarily unavailable. Please try again.'
    : 'Please check the highlighted fields and try again.'
  return new ApiError(status,
    typeof envelope.code === 'string' ? envelope.code.slice(0, 80) : 'request_failed',
    typeof details.detail === 'string' ? details.detail.slice(0, 500) : fallback, fields)
}
export interface RequestOptions {
  method?: 'GET' | 'HEAD' | 'POST' | 'PATCH' | 'DELETE'
  body?: unknown
  access?: string | undefined
  csrf?: string | undefined
  share?: { pollId: string; token: string } | undefined
  signal?: AbortSignal | undefined
}
export function shareReadable(path: string, pollId: string): boolean {
  const prefix = '/api/v2/polls/' + encodeURIComponent(pollId) + '/'
  return path === prefix || path === prefix + 'results/' || path === prefix + 'options/'
    || (path.startsWith(prefix + 'options/') && /^[-a-f0-9]+\/$/i.test(path.slice((prefix + 'options/').length)))
}
export class HttpClient {
  async request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const url = apiPath(path)
    const method = options.method || 'GET'
    const headers = new Headers({ Accept: 'application/json' })
    if (options.access) headers.set('Authorization', 'Bearer ' + options.access)
    if (options.csrf) headers.set('X-CSRFToken', options.csrf)
    if (options.body !== undefined) headers.set('Content-Type', 'application/json')
    if (options.share) {
      if (!['GET', 'HEAD'].includes(method) || !shareReadable(url, options.share.pollId)) {
        throw new ApiError(0, 'unsafe_share_scope', 'This private link does not allow that action.')
      }
      headers.set('X-Poll-Share', options.share.token)
    }
    options.signal?.throwIfAborted()
    let response: Response
    try {
      response = await fetch(url, {
        method, headers, credentials: 'same-origin', cache: 'no-store', redirect: 'error',
        ...(options.signal ? { signal: options.signal } : {}),
        ...(options.body !== undefined ? { body: JSON.stringify(options.body) } : {}),
      })
    } catch {
      if (options.signal?.aborted) throw new DOMException('Request cancelled', 'AbortError')
      throw new ApiError(0, 'network_error', 'Cannot reach Project Nexus. Check your connection and try again.')
    }
    options.signal?.throwIfAborted()
    let data: unknown
    if (response.status !== 204 && method !== 'HEAD') {
      try { data = await response.json() } catch { data = undefined }
    }
    options.signal?.throwIfAborted()
    if (!response.ok) throw responseError(response.status, data)
    if (response.status !== 204 && method !== 'HEAD' && data === undefined) {
      throw new ApiError(502, 'invalid_response', 'The service returned an unexpected response.')
    }
    return data as T
  }
}
