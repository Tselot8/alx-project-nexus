import { describe, expect, it, vi } from 'vitest'
import { HttpClient } from './http'
import { ApiClient } from './client'
import { Session } from '../auth/session'
import { ShareVault, capturePrivateShare } from '../features/sharing/share-vault'
import { failure, json, network, otherPollId, pollId, shareData } from '../test/network'

describe('typed transport and cancellation', () => {
  it.each(['https://other.example.invalid/api/v2/polls/', '//other.example.invalid/api/v2/polls/',
    '/api/v2/../../unrelated/', '/api/v2/polls/%2fescape', '/api/v2/polls/?token=not-allowed'])(
    'refuses unsafe request target %s before sending credentials', async path => {
      const fetcher = network(() => json({}))
      await expect(new HttpClient().request(path, { access: 'test-access' })).rejects.toMatchObject({ code: 'unsafe_request' })
      expect(fetcher).not.toHaveBeenCalled()
    })
  it('uses same-origin cookies, no-store, and forbids redirects', async () => {
    network((_path, init) => {
      expect(init.credentials).toBe('same-origin')
      expect(init.cache).toBe('no-store')
      expect(init.redirect).toBe('error')
      return json({ ok: true })
    })
    expect(await new HttpClient().request('/api/v2/polls/')).toEqual({ ok: true })
  })
  it('maps the actual v2 error envelope and field errors', async () => {
    network(() => failure(400, { email: ['Enter a valid email.'] }, 'invalid'))
    await expect(new HttpClient().request('/api/v2/auth/register/')).rejects.toMatchObject({
      status: 400, code: 'invalid', fieldErrors: { email: ['Enter a valid email.'] },
    })
  })
  it('does not surface HTML error bodies or network diagnostics', async () => {
    network(() => new Response('<html>internal debug details</html>', { status: 500 }))
    await expect(new HttpClient().request('/api/v2/polls/')).rejects.toMatchObject({
      status: 500, message: 'The service is temporarily unavailable. Please try again.',
    })
    network(() => { throw new Error('internal sensitive diagnostic') })
    await expect(new HttpClient().request('/api/v2/polls/')).rejects.toMatchObject({
      code: 'network_error', message: 'Cannot reach Project Nexus. Check your connection and try again.',
    })
  })
  it('passes cancellation to fetch and rejects an aborted response', async () => {
    const controller = new AbortController()
    network((_path, init) => {
      expect(init.signal).toBe(controller.signal)
      controller.abort()
      return json({ ok: true })
    })
    await expect(new HttpClient().request('/api/v2/polls/', { signal: controller.signal })).rejects.toMatchObject({ name: 'AbortError' })
  })
})

describe('fragment capabilities never become general credentials', () => {
  const token = 'a'.repeat(43)
  it('strips the fragment before resolution and retains scope only in memory', async () => {
    window.history.replaceState({}, '', '/polls/' + pollId + '#share=' + token)
    const write = vi.spyOn(Storage.prototype, 'setItem')
    const captured = capturePrivateShare(window)
    expect(window.location.hash).toBe('')
    expect(window.location.pathname).toBe('/polls/' + pollId)
    network((path, init) => {
      expect(window.location.hash).toBe('')
      expect(path).toBe('/api/v2/shares/resolve/')
      expect(init.method).toBe('POST')
      expect(JSON.parse(String(init.body))).toEqual({ token })
      expect(new Headers(init.headers).has('Authorization')).toBe(false)
      return json(shareData())
    })
    const vault = new ShareVault(new HttpClient())
    expect(captured).not.toBeNull()
    await vault.resolve(captured!)
    expect(vault.credential('/api/v2/polls/' + pollId + '/', 'GET')).toEqual({ pollId, token })
    expect(write).not.toHaveBeenCalled()
    expect(JSON.stringify(vault)).not.toContain(token)
  })
  it.each(['bad', 'a'.repeat(43) + '&extra=1'])('removes an invalid credential fragment without a request', async raw => {
    window.history.replaceState({}, '', '/polls/' + pollId + '#share=' + raw)
    const fetcher = network(() => json({}))
    const captured = capturePrivateShare(window)
    expect(window.location.hash).toBe('')
    expect(captured).toEqual({ invalid: true })
    await expect(new ShareVault(new HttpClient()).resolve(captured!)).rejects.toMatchObject({ status: 400 })
    expect(fetcher).not.toHaveBeenCalled()
  })
  it('leaves ordinary accessibility anchors alone', () => {
    window.history.replaceState({}, '', '/#main-content')
    expect(capturePrivateShare(window)).toBeNull()
    expect(window.location.hash).toBe('#main-content')
  })
  it('rejects a resolver returning another poll', async () => {
    network(() => json(shareData(otherPollId)))
    const vault = new ShareVault(new HttpClient())
    await expect(vault.resolve({ token, expectedPoll: pollId })).rejects.toMatchObject({ status: 404 })
    expect(vault.credential('/api/v2/polls/' + otherPollId + '/', 'GET')).toBeUndefined()
  })
  it('scopes the header to matching read paths only, never voting or auth', async () => {
    network(() => json(shareData()))
    const vault = new ShareVault(new HttpClient())
    await vault.resolve({ token, expectedPoll: pollId })
    for (const suffix of ['', 'options/', 'results/']) {
      expect(vault.credential('/api/v2/polls/' + pollId + '/' + suffix, 'GET')).toEqual({ pollId, token })
    }
    for (const path of [
      '/api/v2/auth/me/', '/api/v2/polls/', '/api/v2/polls/' + otherPollId + '/',
      '/api/v2/polls/' + pollId + '/ballots/', '/api/v2/polls/' + pollId + '/share/',
    ]) expect(vault.credential(path, 'GET')).toBeUndefined()
    expect(vault.credential('/api/v2/polls/' + pollId + '/', 'PATCH')).toBeUndefined()
    const http = new HttpClient()
    const api = new ApiClient(http, new Session(http), vault)
    network((path, init) => {
      expect(new Headers(init.headers).get('X-Poll-Share')).toBe(
        path === '/api/v2/polls/' + pollId + '/results/' ? token : null)
      return json({})
    })
    await api.request('/api/v2/polls/' + pollId + '/results/')
    await api.request('/api/v2/auth/me/')
    await api.request('/api/v2/polls/' + otherPollId + '/')
  })
  it('has a second transport guard against accidentally forwarding share credentials', async () => {
    const http = new HttpClient()
    const fetcher = network(() => json({}))
    await expect(http.request('/api/v2/auth/me/', { share: { pollId, token } })).rejects.toMatchObject({ code: 'unsafe_share_scope' })
    await expect(http.request('/api/v2/polls/' + pollId + '/', { method: 'POST', share: { pollId, token } })).rejects.toMatchObject({ code: 'unsafe_share_scope' })
    expect(fetcher).not.toHaveBeenCalled()
  })
  it('does not retain a cancelled resolution or a capability after clear', async () => {
    const controller = new AbortController()
    network(() => { controller.abort(); return json(shareData()) })
    const vault = new ShareVault(new HttpClient())
    await expect(vault.resolve({ token, expectedPoll: pollId }, controller.signal)).rejects.toMatchObject({ name: 'AbortError' })
    expect(vault.credential('/api/v2/polls/' + pollId + '/', 'GET')).toBeUndefined()
    network(() => json(shareData()))
    await vault.resolve({ token, expectedPoll: pollId })
    vault.clear()
    expect(vault.credential('/api/v2/polls/' + pollId + '/', 'GET')).toBeUndefined()
  })
})
