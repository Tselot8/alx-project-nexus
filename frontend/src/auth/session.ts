import type { Account, Credentials, RefreshResponse, Registration, SessionResponse } from '../api/contracts'
import { ApiError, HttpClient, isRecord } from '../api/http'

export type SessionSnapshot =
  | { status: 'restoring' }
  | { status: 'anonymous' }
  | { status: 'unavailable'; message: string }
  | { status: 'authenticated'; user: Account }

function account(value: unknown): Account {
  if (!isRecord(value) || typeof value.id !== 'string' || typeof value.username !== 'string'
    || typeof value.email !== 'string' || !isRecord(value.profile)
    || ![null, 'string'].includes(value.profile.bio === null ? null : typeof value.profile.bio)
    || ![null, 'string'].includes(value.profile.location === null ? null : typeof value.profile.location)) {
    throw new ApiError(502, 'invalid_response', 'The account response was not valid.')
  }
  return {
    id: value.id, username: value.username, email: value.email,
    profile: {
      bio: value.profile.bio as string | null,
      location: value.profile.location as string | null,
    },
  }
}
function access(value: RefreshResponse): void {
  if (!value || typeof value.access !== 'string' || !value.access
    || !Number.isFinite(value.expires_in) || value.expires_in <= 0) {
    throw new ApiError(502, 'invalid_response', 'The session response was not valid.')
  }
}
const changed = () => new DOMException('Session changed', 'AbortError')

/** No credentials enter React Query, browser storage, URLs or logging.
 * All cookie mutations share a queue and, where available, a cross-tab Web Lock.
 */
export class Session {
  #state: SessionSnapshot = { status: 'restoring' }
  #listeners = new Set<() => void>()
  #access: string | undefined
  #expiresAt = 0
  #csrf: string | undefined
  #csrfFlight: Promise<string> | undefined
  #restoreFlight: Promise<void> | undefined
  #refreshFlight: Promise<string> | undefined
  #tail: Promise<unknown> = Promise.resolve()
  #epoch = 0
  #accountRevision = 0

  constructor(private http: HttpClient, private clearPrivateData: () => void = () => {}) {}
  get generation() { return this.#epoch }
  getSnapshot = (): SessionSnapshot => this.#state
  subscribe = (listener: () => void) => {
    this.#listeners.add(listener)
    return () => { this.#listeners.delete(listener) }
  }
  #publish(state: SessionSnapshot) {
    this.#state = state
    for (const listener of this.#listeners) listener()
  }
  #forget(state: SessionSnapshot) {
    this.#access = undefined
    this.#expiresAt = 0
    this.clearPrivateData()
    this.#publish(state)
  }
  #check(epoch: number) { if (epoch !== this.#epoch) throw changed() }
  #adopt(user: Account, token: RefreshResponse, epoch: number) {
    this.#check(epoch)
    access(token)
    if (this.#state.status === 'authenticated' && this.#state.user.id !== user.id) this.#epoch++
    if (this.#state.status !== 'authenticated' || this.#state.user.id !== user.id) {
      this.clearPrivateData()
    }
    this.#access = token.access
    this.#expiresAt = Date.now() + token.expires_in * 1000
    this.#publish({ status: 'authenticated', user })
  }
  #schedule<T>(action: () => Promise<T>): Promise<T> {
    const locked = () => typeof navigator !== 'undefined' && navigator.locks
      ? navigator.locks.request('nexus-auth-cookie', { mode: 'exclusive' }, action)
      : action()
    const pending = this.#tail.then(locked, locked)
    this.#tail = pending.then(() => {}, () => {})
    return pending
  }
  async #getCsrf(force = false): Promise<string> {
    if (force) this.#csrf = undefined
    if (this.#csrf) return this.#csrf
    if (this.#csrfFlight) return this.#csrfFlight
    const pending = this.http.request<{ csrf_token: string }>('/api/v2/auth/csrf/')
      .then(data => {
        if (typeof data.csrf_token !== 'string' || !data.csrf_token) {
          throw new ApiError(502, 'invalid_response', 'Could not prepare a secure request.')
        }
        this.#csrf = data.csrf_token
        return data.csrf_token
      })
    this.#csrfFlight = pending
    try { return await pending } finally { this.#csrfFlight = undefined }
  }
  async #cookiePost<T>(path: string, body: unknown = {}, accessToken?: string): Promise<T> {
    const send = async () => this.http.request<T>(path, {
      method: 'POST', body, csrf: await this.#getCsrf(), access: accessToken,
    })
    try { return await send() } catch (error) {
      // The backend rejects CSRF in initial(), before any handler side effects.
      // A second tab may have rotated its CSRF cookie after login.
      if (!(error instanceof ApiError) || error.status !== 403
        || error.message !== 'CSRF verification failed.') throw error
      await this.#getCsrf(true)
      return send()
    }
  }
  #failed(error: unknown, epoch: number) {
    if (epoch !== this.#epoch) return
    this.#forget(error instanceof ApiError && error.status === 401
      ? { status: 'anonymous' }
      : { status: 'unavailable', message: 'We could not verify your session. Please retry.' })
  }
  restore = (retry = false): Promise<void> => {
    if (this.#restoreFlight) return this.#restoreFlight
    if (this.#state.status !== 'restoring' && !retry) return Promise.resolve()
    const epoch = this.#epoch
    this.#publish({ status: 'restoring' })
    const pending = this.refresh().then(() => {}, error => { this.#failed(error, epoch) })
    this.#restoreFlight = pending
    void pending.finally(() => { this.#restoreFlight = undefined })
    return pending
  }
  refresh = (rejectedAccess?: string): Promise<string> => {
    if (rejectedAccess && this.#access && this.#access !== rejectedAccess) {
      return Promise.resolve(this.#access)
    }
    if (this.#refreshFlight) return this.#refreshFlight
    const epoch = this.#epoch
    const pending = this.#schedule(async () => {
      this.#check(epoch)
      try {
        const token = await this.#cookiePost<RefreshResponse>('/api/v2/auth/refresh/')
        this.#check(epoch)
        access(token)
        const revision = this.#accountRevision
        const data = await this.http.request<{ user: Account }>('/api/v2/auth/me/', { access: token.access })
        const user = account(data.user)
        const current = this.#state
        // Do not overwrite a just-confirmed profile update with an older me response.
        this.#adopt(revision !== this.#accountRevision && current.status === 'authenticated' && current.user.id === user.id ? current.user : user, token, epoch)
        return token.access
      } catch (error) { this.#failed(error, epoch); throw error }
    })
    this.#refreshFlight = pending
    void pending.finally(() => {
      if (this.#refreshFlight === pending) this.#refreshFlight = undefined
    }).catch(() => {})
    return pending
  }
  expire(rejectedAccess: string) {
    if (this.#access !== rejectedAccess) return
    this.#epoch++
    this.#forget({ status: 'anonymous' })
  }
  async token(): Promise<string> {
    if (this.#state.status === 'restoring') await this.restore()
    if (this.#state.status !== 'authenticated') {
      throw new ApiError(this.#state.status === 'unavailable' ? 503 : 401,
        'session_required', 'Please sign in to continue.')
    }
    if (this.#access && Date.now() + 5000 < this.#expiresAt) return this.#access
    return this.refresh()
  }
  async #authenticate(path: string, body: Credentials | Registration): Promise<void> {
    const epoch = ++this.#epoch
    this.#forget({ status: 'restoring' })
    return this.#schedule(async () => {
      this.#check(epoch)
      try {
        const data = await this.#cookiePost<SessionResponse>(path, body)
        this.#check(epoch)
        if (typeof data.csrf_token !== 'string' || !data.csrf_token) {
          throw new ApiError(502, 'invalid_response', 'The session response was not valid.')
        }
        this.#csrf = data.csrf_token
        this.#adopt(account(data.user), data, epoch)
      } catch (error) {
        if (epoch === this.#epoch) this.#forget({ status: 'anonymous' })
        throw error
      }
    })
  }
  adoptAccount(value: unknown, epoch: number) {
    this.#check(epoch)
    const user = account(value)
    if (this.#state.status !== 'authenticated' || this.#state.user.id !== user.id) throw changed()
    this.#accountRevision++
    this.#publish({ status: 'authenticated', user })
    return user
  }
  async changePassword(currentPassword: string, newPassword: string) {
    const epoch = this.#epoch
    const token = await this.token()
    this.#check(epoch)
    return this.#schedule(async () => {
      this.#check(epoch)
      try {
        await this.#cookiePost<void>('/api/v2/auth/password/change/', {
          current_password: currentPassword, new_password: newPassword,
        }, token)
        this.#check(epoch)
        this.#epoch++
        this.#csrf = undefined
        this.#forget({ status: 'anonymous' })
      } catch (error) {
        if (epoch === this.#epoch && error instanceof ApiError) {
          if (error.status === 401) this.expire(token)
          else if (error.status === 0 || error.status >= 500) {
            // An interrupted response may follow a committed password change.
            this.#epoch++
            this.#forget({ status: 'anonymous' })
          }
        }
        throw error
      }
    })
  }
  login = (values: Credentials) => this.#authenticate('/api/v2/auth/login/', values)
  register = (values: Registration) => this.#authenticate('/api/v2/auth/register/', values)
  logout = (): Promise<void> => {
    const epoch = ++this.#epoch
    // Clear local identity immediately; then revoke the latest rotated cookie.
    this.#forget({ status: 'anonymous' })
    return this.#schedule(async () => {
      try { await this.#cookiePost<void>('/api/v2/auth/logout/') }
      catch (error) {
        // A missing/revoked cookie already has no server session to terminate.
        if (!(error instanceof ApiError && error.status === 401)) throw error
      } finally {
        if (epoch === this.#epoch) this.#forget({ status: 'anonymous' })
      }
    })
  }
}
