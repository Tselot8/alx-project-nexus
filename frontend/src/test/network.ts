import { vi } from 'vitest'
import type { Account } from '../api/contracts'

export const alice: Account = {
  id: '11111111-1111-4111-8111-111111111111', username: 'Alice', email: 'alice@example.invalid',
  profile: { bio: null, location: null },
}
export const bob: Account = { ...alice, id: '22222222-2222-4222-8222-222222222222', username: 'Bob', email: 'bob@example.invalid' }
export const pollId = '33333333-3333-4333-8333-333333333333'
export const otherPollId = '44444444-4444-4444-8444-444444444444'
export const sessionData = (access = 'test-access-one', user = alice) => ({
  user, access, expires_in: 300, csrf_token: 'test-csrf-rotated',
})
export function json(data: unknown, status = 200) {
  return new Response(status === 204 ? null : JSON.stringify(data), {
    status, headers: { 'Content-Type': 'application/json' },
  })
}
export const failure = (status: number, details: unknown = { detail: 'Rejected.' }, code = 'request_failed') =>
  json({ error: { code, details } }, status)
export function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (value: unknown) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
export function network(handler: (path: string, init: RequestInit) => Response | Promise<Response>) {
  const fetcher = vi.fn((input: RequestInfo | URL, init: RequestInit = {}) => Promise.resolve(handler(String(input), init)))
  vi.stubGlobal('fetch', fetcher)
  return fetcher
}
export function anonymousNetwork() {
  return network(path => {
    if (path === '/api/v2/auth/csrf/') return json({ csrf_token: 'test-csrf' })
    if (path === '/api/v2/auth/refresh/') return failure(401)
    throw new Error('Unexpected test network request.')
  })
}
export function shareData(id = pollId) {
  return { poll: { id, visibility: 'private' }, share: { poll_id: id, header: 'X-Poll-Share' } }
}
