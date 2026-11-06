import { act, render, screen, waitFor } from '@testing-library/react'
import { expect, it } from 'vitest'
import { MemoryRouter } from 'react-router'
import { App } from '../../app/app'
import { Providers } from '../../app/providers'
import { createServices } from '../../app/services'
import { deferred, failure, json, network, publicPoll } from '../../test/network'

it('rebuilds discovery observers if anonymous restoration clears pending public queries', async () => {
  const refresh = deferred<Response>()
  const publicRead = deferred<Response>()
  const categoriesRead = deferred<Response>()
  let polls = 0, categories = 0
  const page = { count: 1, next: null, previous: null, results: [publicPoll] }
  network(path => {
    if (path.endsWith('/csrf/')) return json({ csrf_token: 'fixture-csrf' })
    if (path.endsWith('/refresh/')) return refresh.promise
    if (path.startsWith('/api/v2/categories/')) return ++categories === 1
      ? categoriesRead.promise : json({ count: 0, next: null, previous: null, results: [] })
    if (path.startsWith('/api/v2/polls/?')) return ++polls === 1 ? publicRead.promise : json(page)
    return failure(404)
  })
  const services = createServices()
  services.queryClient.setDefaultOptions({ queries: { retry: false } })
  render(<Providers services={services}><MemoryRouter initialEntries={['/polls']}><App /></MemoryRouter></Providers>)
  await waitFor(() => { expect(polls).toBe(1); expect(categories).toBe(1) })
  await act(async () => { refresh.resolve(failure(401)) })
  try {
    await waitFor(() => { expect(polls).toBeGreaterThan(1); expect(categories).toBeGreaterThan(1) })
    expect(await screen.findByRole('link', { name: publicPoll.question })).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByText('Loading public polls\u2026')).not.toBeInTheDocument())
    expect(services.session.getSnapshot().status).toBe('anonymous')
  } finally {
    await act(async () => {
      publicRead.resolve(json(page))
      categoriesRead.resolve(json({ count: 0, next: null, previous: null, results: [] }))
    })
  }
})
