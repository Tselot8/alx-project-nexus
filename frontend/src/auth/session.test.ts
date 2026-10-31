import { describe, expect, it, vi } from 'vitest'
import { waitFor } from '@testing-library/react'
import { ApiClient } from '../api/client'
import { ApiError, HttpClient } from '../api/http'
import { ShareVault } from '../features/sharing/share-vault'
import { Session } from './session'
import { alice, bob, deferred, failure, json, network, sessionData } from '../test/network'

const credentials = { email: alice.email, password: 'test-only-long-password' }
function fixture() {
  const http = new HttpClient()
  const clear = vi.fn()
  const session = new Session(http, clear)
  return { session, clear, api: new ApiClient(http, session, new ShareVault(http)) }
}
function loginRoutes(path: string) {
  if (path.endsWith('/csrf/')) return json({ csrf_token: 'test-csrf' })
  if (path.endsWith('/login/') || path.endsWith('/register/')) return json(sessionData(), path.endsWith('/register/') ? 201 : 200)
  if (path.endsWith('/me/')) return json({ user: alice })
  throw new Error('Unexpected test request.')
}

describe('session and real request contracts', () => {
  it('bootstraps CSRF and restores from the cookie with one refresh and me request', async () => {
    const fetcher = network((path, init) => {
      if (path.endsWith('/refresh/')) {
        expect(new Headers(init.headers).get('X-CSRFToken')).toBe('test-csrf')
        expect(init.credentials).toBe('same-origin')
        expect(new Headers(init.headers).has('Authorization')).toBe(false)
        return json({ access: 'restored-access', expires_in: 300 })
      }
      return loginRoutes(path)
    })
    const { session } = fixture()
    await Promise.all([session.restore(), session.restore(), session.restore()])
    expect(session.getSnapshot()).toEqual({ status: 'authenticated', user: alice })
    expect(fetcher.mock.calls.map(([path]) => path)).toEqual([
      '/api/v2/auth/csrf/', '/api/v2/auth/refresh/', '/api/v2/auth/me/',
    ])
    expect(new Headers(fetcher.mock.calls[2]?.[1]?.headers).get('Authorization')).toBe('Bearer restored-access')
  })
  it('uses the rotated CSRF token for logout and clears local identity', async () => {
    network((path, init) => {
      if (path.endsWith('/login/')) {
        expect(JSON.parse(String(init.body))).toEqual(credentials)
        expect(new Headers(init.headers).get('X-CSRFToken')).toBe('test-csrf')
      }
      if (path.endsWith('/logout/')) {
        expect(new Headers(init.headers).get('X-CSRFToken')).toBe('test-csrf-rotated')
        expect(new Headers(init.headers).has('Authorization')).toBe(false)
        return json(null, 204)
      }
      return loginRoutes(path)
    })
    const { session, clear } = fixture()
    await session.login(credentials)
    await session.logout()
    expect(session.getSnapshot()).toEqual({ status: 'anonymous' })
    expect(clear).toHaveBeenCalled()
    await expect(session.token()).rejects.toMatchObject({ status: 401 })
  })
  it('registers with the backend username/email/password allowlist', async () => {
    network((path, init) => {
      if (path.endsWith('/register/')) expect(JSON.parse(String(init.body))).toEqual({ ...credentials, username: 'Alice' })
      return loginRoutes(path)
    })
    const { session } = fixture()
    await session.register({ ...credentials, username: 'Alice' })
    expect(session.getSnapshot()).toEqual({ status: 'authenticated', user: alice })
  })
  it('keeps access and CSRF credentials out of browser storage and observable state', async () => {
    const local = vi.spyOn(Storage.prototype, 'setItem')
    network(loginRoutes)
    const { session } = fixture()
    await session.login(credentials)
    expect(JSON.stringify(session.getSnapshot())).not.toContain('test-access')
    expect(JSON.stringify(session.getSnapshot())).not.toContain('test-csrf')
    expect(JSON.stringify(session)).not.toContain('test-access')
    expect(local).not.toHaveBeenCalled()
    expect(window.localStorage.length).toBe(0)
    expect(window.sessionStorage.length).toBe(0)
  })
  it('does not refresh after rejected login credentials', async () => {
    const fetcher = network(path => path.endsWith('/csrf/')
      ? json({ csrf_token: 'test-csrf' }) : failure(401))
    const { session } = fixture()
    await expect(session.login(credentials)).rejects.toMatchObject({ status: 401 })
    expect(session.getSnapshot().status).toBe('anonymous')
    expect(fetcher).toHaveBeenCalledTimes(2)
  })
  it('exposes registration field errors without placing credentials in state', async () => {
    network(path => path.endsWith('/csrf/') ? json({ csrf_token: 'test-csrf' })
      : failure(400, { password: ['This password is too common.'] }, 'invalid'))
    const { session } = fixture()
    await expect(session.register({ ...credentials, username: 'Alice' })).rejects.toMatchObject({
      status: 400, fieldErrors: { password: ['This password is too common.'] },
    })
    expect(session.getSnapshot().status).toBe('anonymous')
  })
  it('treats missing, revoked and inactive refresh sessions as anonymous', async () => {
    network(path => path.endsWith('/csrf/') ? json({ csrf_token: 'test-csrf' }) : failure(401))
    const { session } = fixture()
    await session.restore()
    expect(session.getSnapshot().status).toBe('anonymous')
  })
  it('preserves a recoverable unavailable state on network failure', async () => {
    let online = false
    network(path => {
      if (path.endsWith('/refresh/')) {
        if (!online) throw new TypeError('network unavailable')
        return json({ access: 'recovered-access', expires_in: 300 })
      }
      return loginRoutes(path)
    })
    const { session } = fixture()
    await session.restore()
    expect(session.getSnapshot().status).toBe('unavailable')
    online = true
    await session.restore(true)
    expect(session.getSnapshot().status).toBe('authenticated')
  })
  it('re-bootstraps once after a genuine CSRF rejection', async () => {
    let csrf = 0
    let posts = 0
    network((path, init) => {
      if (path.endsWith('/csrf/')) return json({ csrf_token: 'csrf-' + ++csrf })
      if (path.endsWith('/login/')) {
        posts++
        if (posts === 1) return failure(403, { detail: 'CSRF verification failed.' }, 'permission_denied')
        expect(new Headers(init.headers).get('X-CSRFToken')).toBe('csrf-2')
        return json(sessionData())
      }
      throw new Error('Unexpected test request.')
    })
    const { session } = fixture()
    await session.login(credentials)
    expect(csrf).toBe(2)
    expect(posts).toBe(2)
  })
  it('never loops on persistent CSRF failure', async () => {
    const fetcher = network(path => path.endsWith('/csrf/') ? json({ csrf_token: 'test-csrf' })
      : failure(403, { detail: 'CSRF verification failed.' }, 'permission_denied'))
    const { session } = fixture()
    await expect(session.login(credentials)).rejects.toMatchObject({ status: 403 })
    expect(fetcher).toHaveBeenCalledTimes(4)
  })
  it('coordinates concurrent 401 responses with exactly one refresh', async () => {
    const rotation = deferred<Response>()
    let refreshes = 0
    let attempts = 0
    network((path, init) => {
      if (path === '/api/v2/private-test/') {
        attempts++
        return new Headers(init.headers).get('Authorization') === 'Bearer renewed-access'
          ? json({ ok: true }) : failure(401)
      }
      if (path.endsWith('/refresh/')) { refreshes++; return rotation.promise }
      return loginRoutes(path)
    })
    const { session, api } = fixture()
    await session.login(credentials)
    const pending = Array.from({ length: 8 }, () => api.request('/api/v2/private-test/', { auth: 'required' }))
    await waitFor(() => expect(refreshes).toBe(1))
    rotation.resolve(json({ access: 'renewed-access', expires_in: 300 }))
    expect(await Promise.all(pending)).toEqual(Array(8).fill({ ok: true }))
    expect(refreshes).toBe(1)
    expect(attempts).toBe(16)
  })
  it('retries a protected request once, then clears a rejected renewed session', async () => {
    let refreshes = 0
    let requests = 0
    network(path => {
      if (path === '/api/v2/private-test/') { requests++; return failure(401) }
      if (path.endsWith('/refresh/')) { refreshes++; return json({ access: 'renewed-access', expires_in: 300 }) }
      return loginRoutes(path)
    })
    const { session, api } = fixture()
    await session.login(credentials)
    await expect(api.request('/api/v2/private-test/', { auth: 'required' })).rejects.toMatchObject({ status: 401 })
    expect(requests).toBe(2)
    expect(refreshes).toBe(1)
    expect(session.getSnapshot().status).toBe('anonymous')
  })
  it('does not revive state when logout overlaps a pending refresh', async () => {
    const rotation = deferred<Response>()
    let refreshes = 0
    let logouts = 0
    network(path => {
      if (path.endsWith('/refresh/')) { refreshes++; return rotation.promise }
      if (path.endsWith('/logout/')) { logouts++; return json(null, 204) }
      return loginRoutes(path)
    })
    const { session } = fixture()
    await session.login(credentials)
    const refreshing = session.refresh()
    const rejected = expect(refreshing).rejects.toMatchObject({ name: 'AbortError' })
    await waitFor(() => expect(refreshes).toBe(1))
    const logout = session.logout()
    expect(session.getSnapshot().status).toBe('anonymous')
    rotation.resolve(json({ access: 'must-not-revive', expires_in: 300 }))
    await rejected
    await logout
    expect(logouts).toBe(1)
    expect(session.getSnapshot().status).toBe('anonymous')
  })
  it('reports an unconfirmed server logout while still clearing local credentials', async () => {
    network(path => {
      if (path.endsWith('/logout/')) throw new TypeError('offline')
      return loginRoutes(path)
    })
    const { session } = fixture()
    await session.login(credentials)
    await expect(session.logout()).rejects.toBeInstanceOf(ApiError)
    expect(session.getSnapshot().status).toBe('anonymous')
    await expect(session.token()).rejects.toMatchObject({ status: 401 })
  })
  it('fences requests when a refresh discovers a different account in another tab', async () => {
    let renewed = false
    network(path => {
      if (path === '/api/v2/private-test/') return failure(401)
      if (path.endsWith('/refresh/')) { renewed = true; return json({ access: 'bob-access', expires_in: 300 }) }
      if (path.endsWith('/me/') && renewed) return json({ user: bob })
      return loginRoutes(path)
    })
    const { session, api, clear } = fixture()
    await session.login(credentials)
    const cleared = clear.mock.calls.length
    await expect(api.request('/api/v2/private-test/', { auth: 'required' })).rejects.toMatchObject({ name: 'AbortError' })
    expect(session.getSnapshot()).toEqual({ status: 'authenticated', user: bob })
    expect(clear.mock.calls.length).toBeGreaterThan(cleared)
  })
  it('reuses the current access token for a late 401 from the previous token', async () => {
    const late = deferred<Response>()
    let old = 0
    let refreshes = 0
    network((path, init) => {
      if (path === '/api/v2/private-test/') {
        if (new Headers(init.headers).get('Authorization') === 'Bearer renewed-access') return json({ ok: true })
        old++
        return old === 1 ? late.promise : failure(401)
      }
      if (path.endsWith('/refresh/')) { refreshes++; return json({ access: 'renewed-access', expires_in: 300 }) }
      return loginRoutes(path)
    })
    const { session, api } = fixture()
    await session.login(credentials)
    const slow = api.request('/api/v2/private-test/', { auth: 'required' })
    expect(await api.request('/api/v2/private-test/', { auth: 'required' })).toEqual({ ok: true })
    late.resolve(failure(401))
    expect(await slow).toEqual({ ok: true })
    expect(refreshes).toBe(1)
  })
  it('refreshes near expiration before sending a protected request', async () => {
    const now = vi.spyOn(Date, 'now').mockReturnValue(1_000_000)
    let refreshes = 0
    network(path => {
      if (path.endsWith('/refresh/')) { refreshes++; return json({ access: 'renewed-access', expires_in: 300 }) }
      return loginRoutes(path)
    })
    const { session } = fixture()
    await session.login(credentials)
    now.mockReturnValue(1_296_000)
    expect(await Promise.all([session.token(), session.token()])).toEqual(['renewed-access', 'renewed-access'])
    expect(refreshes).toBe(1)
  })
  it('uses a shared Web Lock to serialize cookie rotation across tabs', async () => {
    let tail: Promise<unknown> = Promise.resolve()
    const original = Object.getOwnPropertyDescriptor(navigator, 'locks')
    const request = vi.fn((_name: string, _options: unknown, action: () => Promise<unknown>) => {
      const pending = tail.then(action)
      tail = pending.then(() => {}, () => {})
      return pending
    })
    Object.defineProperty(navigator, 'locks', { configurable: true, value: { request } })
    let active = 0
    let maximum = 0
    network(async path => {
      if (path.endsWith('/refresh/')) {
        active++; maximum = Math.max(maximum, active)
        await Promise.resolve()
        active--
        return json({ access: 'restored-access', expires_in: 300 })
      }
      return loginRoutes(path)
    })
    try {
      const first = fixture().session
      const second = fixture().session
      await Promise.all([first.restore(), second.restore()])
      expect(first.getSnapshot().status).toBe('authenticated')
      expect(second.getSnapshot().status).toBe('authenticated')
      expect(maximum).toBe(1)
      expect(request).toHaveBeenCalledTimes(2)
    } finally {
      if (original) Object.defineProperty(navigator, 'locks', original)
      else Reflect.deleteProperty(navigator, 'locks')
    }
  })
  it('logs out a session whose pending login rotated the CSRF cookie', async () => {
    const reply = deferred<Response>()
    let csrf = 'csrf-before'
    let logins = 0
    let logouts = 0
    network((path, init) => {
      if (path.endsWith('/csrf/')) return json({ csrf_token: csrf })
      if (path.endsWith('/login/')) {
        logins++
        return reply.promise.then(response => { csrf = 'test-csrf-rotated'; return response })
      }
      if (path.endsWith('/logout/')) {
        logouts++
        return new Headers(init.headers).get('X-CSRFToken') === csrf
          ? json(null, 204) : failure(403, { detail: 'CSRF verification failed.' }, 'permission_denied')
      }
      throw new Error('Unexpected test request.')
    })
    const { session } = fixture()
    const login = session.login(credentials)
    const rejected = expect(login).rejects.toMatchObject({ name: 'AbortError' })
    await waitFor(() => expect(logins).toBe(1))
    const logout = session.logout()
    reply.resolve(json(sessionData()))
    await rejected
    await logout
    expect(logouts).toBe(2)
    expect(session.getSnapshot().status).toBe('anonymous')
  })
  it('does not refresh or sign out on a protected permission denial', async () => {
    let refreshes = 0
    network(path => {
      if (path === '/api/v2/private-test/') return failure(403)
      if (path.endsWith('/refresh/')) { refreshes++; return failure(401) }
      return loginRoutes(path)
    })
    const { session, api } = fixture()
    await session.login(credentials)
    await expect(api.request('/api/v2/private-test/', { auth: 'required' })).rejects.toMatchObject({ status: 403 })
    expect(refreshes).toBe(0)
    expect(session.getSnapshot().status).toBe('authenticated')
  })
  it('discards a protected data response that arrives after logout', async () => {
    const reply = deferred<Response>()
    let reads = 0
    network(path => {
      if (path === '/api/v2/private-test/') { reads++; return reply.promise }
      if (path.endsWith('/logout/')) return json(null, 204)
      return loginRoutes(path)
    })
    const { session, api } = fixture()
    await session.login(credentials)
    const read = api.request('/api/v2/private-test/', { auth: 'required' })
    const rejected = expect(read).rejects.toMatchObject({ name: 'AbortError' })
    await waitFor(() => expect(reads).toBe(1))
    await session.logout()
    reply.resolve(json({ privateData: 'test-only' }))
    await rejected
    expect(session.getSnapshot().status).toBe('anonymous')
  })

})
