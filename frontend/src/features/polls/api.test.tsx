import { Providers } from '../../app/providers'
import { renderHook, waitFor } from '@testing-library/react'
import { expect, it } from 'vitest'
import { createServices } from '../../app/services'
import { discoveryPath, queryKeys, usePublicPolls } from './api'
import { failure, json, network } from '../../test/network'

async function anonymousServices() {
  const services = createServices()
  network(path => path.endsWith('/csrf/') ? json({ csrf_token: 'fixture-csrf' }) : failure(401))
  await services.session.restore()
  return services
}

it('uses the actual public discovery query names and response envelope', async () => {
  const services = await anonymousServices()
  network((path, init) => {
    expect(path).toBe('/api/v2/polls/?q=Tea+%2F+%26+coffee&page=2&sort=newest')
    expect(new Headers(init.headers).has('Authorization')).toBe(false)
    return json({ count: 0, next: null, previous: null, results: [] })
  })
  const filters = { q: 'Tea / & coffee', page: 2, sort: 'newest' as const }
  const { result } = renderHook(() => usePublicPolls(services.api, filters), {
    wrapper: ({ children }) => <Providers services={services}>{children}</Providers>,
  })
  await waitFor(() => expect(result.current.isSuccess).toBe(true))
  expect(result.current.data?.results).toEqual([])
  expect(queryKeys.myPolls('a')).not.toEqual(queryKeys.myPolls('b'))
  expect(discoveryPath({})).toBe('/api/v2/polls/')
})
it('cancels an in-flight discovery request on unmount', async () => {
  const services = await anonymousServices()
  let requestSignal: AbortSignal | null | undefined
  network((_path, init) => new Promise<Response>((_resolve, reject) => {
    requestSignal = init.signal
    init.signal?.addEventListener('abort', () => reject(new DOMException('Cancelled', 'AbortError')))
  }))
  const { unmount } = renderHook(() => usePublicPolls(services.api), {
    wrapper: ({ children }) => <Providers services={services}>{children}</Providers>,
  })
  await waitFor(() => expect(requestSignal).toBeDefined())
  unmount()
  expect(requestSignal?.aborted).toBe(true)
})
