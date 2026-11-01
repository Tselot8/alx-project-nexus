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
    const shareRevision = this.shares.getSnapshot()
    const grantAtStart = this.shares.credential(url, method)
    const send = (token?: string) => this.http.request<T>(url, {
      method, body: options.body, signal: options.signal, access: token,
      share: this.shares.credential(url, method),
    })
    const checkSession = () => {
      options.signal?.throwIfAborted()
      if (shareRevision !== this.shares.getSnapshot() && grantAtStart) {
        throw new DOMException('Share access changed', 'AbortError')
      }
      if (authenticated && generation !== this.session.generation) {
        throw new DOMException('Session changed', 'AbortError')
      }
    }
    const forgetRejectedShare = (error: unknown) => {
      if (!(error instanceof ApiError) || ![403, 404].includes(error.status)) return
      const grant = this.shares.credential(url, method)
      // A results-policy 403 or missing option is not link revocation.
      // Results 404 means the poll itself is inaccessible, not a hidden policy.
      if (grant && (url === '/api/v2/polls/' + grant.pollId + '/'
        || (error.status === 404 && url === '/api/v2/polls/' + grant.pollId + '/results/'))) this.shares.revoke(grant.pollId)
    }
    checkSession()
    try {
      const data = await send(access)
      checkSession()
      return data
    } catch (error) {
      checkSession()
      forgetRejectedShare(error)
      if (!authenticated || !(error instanceof ApiError) || error.status !== 401) throw error
      // Exactly one retry. Auth endpoints use HttpClient directly, never here.
      const replacement = await this.session.refresh(access)
      checkSession()
      try {
        const data = await send(replacement)
        checkSession()
        return data
      } catch (retryError) {
        checkSession()
        forgetRejectedShare(retryError)
        if (retryError instanceof ApiError && retryError.status === 401) this.session.expire(replacement)
        throw retryError
      }
    }
  }
}
