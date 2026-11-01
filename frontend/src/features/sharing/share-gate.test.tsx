import { render, screen, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { Providers } from '../../app/providers'
import { createServices } from '../../app/services'
import { failure, json, network, pollId, publicPoll } from '../../test/network'
import { ShareGate } from './share-gate'

const navigation = vi.hoisted(() => ({ commit: vi.fn() }))
vi.mock('react-router', async importOriginal => ({
  ...await importOriginal<typeof import('react-router')>(),
  useLocation: () => ({ pathname: '/polls/' + pollId, search: '', hash: '#share=' + 's'.repeat(43), state: null, key: 'fragment' }),
  // BrowserRouter commits navigation in a transition. Keep the old hash visible
  // until that commit, so a local state update must not clear an accepted grant.
  useNavigate: () => navigation.commit,
}))

it('does not resolve or clear a reopened fragment twice while navigation is deferred', async () => {
  const fetcher = network(path => {
    if (path.endsWith('/csrf/')) return json({ csrf_token: 'fixture-csrf' })
    if (path.endsWith('/refresh/')) return failure(401)
    if (path === '/api/v2/shares/resolve/') return json({
      poll: { ...publicPoll, visibility: 'private' },
      share: { poll_id: pollId, header: 'X-Poll-Share' },
    })
    return failure(404)
  })
  const services = createServices()
  render(<Providers services={services}><ShareGate captured={null} /></Providers>)
  await waitFor(() => expect(navigation.commit).toHaveBeenCalledWith('/polls/' + pollId, { replace: true }))
  expect(screen.getByText('Checking your private link…')).toBeInTheDocument()
  expect(fetcher.mock.calls.filter(([path]) => path === '/api/v2/shares/resolve/')).toHaveLength(1)
  expect(services.shares.has(pollId)).toBe(true)
})
