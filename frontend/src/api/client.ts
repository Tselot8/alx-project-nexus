import type { Session } from '../auth/session'
import type { ShareVault } from '../features/sharing/share-vault'
import { ApiError, HttpClient, apiPath } from './http'

export class ApiClient {
  constructor(private http: HttpClient, private session: Session, private shares: ShareVault) {}
  async request<T>(path: string, options: {
    auth?: 'none' | 'required'
    method?: 'GET' | 'POST' | 'PATCH' | 'DELETE'
    body?: unknown
    signal?: AbortSignal | undefined
  } = {}): Promise<T> {
    const url = apiPath(path)
    const method = options.method || 'GET'
    const generation = this.session.generation
    const authenticated = options.auth === 'required'
    const access = authenticated ? await this.session.token() : undefined
    const send = (token?: string) => this.http.request<T>(url, {
      method, body: options.body, signal: options.signal, access: token,
      share: this.shares.credential(url, method),
    })
    const checkSession = () => {
      options.signal?.throwIfAborted()
      if (authenticated && generation !== this.session.generation) {
        throw new DOMException('Session changed', 'AbortError')
      }
    }
    checkSession()
    try {
      const data = await send(access)
      checkSession()
      return data
    } catch (error) {
      checkSession()
      if (!authenticated || !(error instanceof ApiError) || error.status !== 401) throw error
      // Exactly one retry. Auth endpoints use HttpClient directly, never here.
      const replacement = await this.session.refresh(access)
      checkSession()
      try {
        const data = await send(replacement)
        checkSession()
        return data
      } catch (retryError) {
        if (retryError instanceof ApiError && retryError.status === 401) this.session.expire(replacement)
        throw retryError
      }
    }
  }
}
