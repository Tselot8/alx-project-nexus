import { StrictMode } from 'react'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation, useNavigate } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import axe from 'axe-core'
import { App } from '../../app/app'
import { Providers } from '../../app/providers'
import { createServices } from '../../app/services'
import type { PollDetail } from '../../api/contracts'
import type { CapturedShare } from '../sharing/share-vault'
import { capturePrivateShare } from '../sharing/share-vault'
import { filtersFromUrl } from '../../pages/explore'
import { alice, bob, deferred, failure, json, network, otherPollId, pollId, publicPoll, sessionData } from '../../test/network'

const category = { id: '55555555-5555-4555-8555-555555555555', name: 'Community', description: null }
const token = 's'.repeat(43)
const page = <T,>(results: T[], count = results.length, next: string | null = null, previous: string | null = null) => ({ results, count, next, previous })
function backend(extra: (path: string, init: RequestInit) => Response | Promise<Response> | undefined = () => undefined) {
  return network((path, init) => {
    const response = extra(path, init)
    if (response) return response
    if (path.endsWith('/csrf/')) return json({ csrf_token: 'csrf-fixture' })
    if (path.endsWith('/refresh/')) return failure(401)
    if (path.startsWith('/api/v2/categories/')) return json(page([category]))
    if (path.startsWith('/api/v2/polls/?') || path === '/api/v2/polls/') return json(page([{ ...publicPoll, category: category.id }]))
    if (path === '/api/v2/polls/' + pollId + '/') return json({ ...publicPoll, category: category.id })
    return failure(404)
  })
}
function LocationProbe() {
  const location = useLocation()
  const navigate = useNavigate()
  return <div><output aria-label="Current route">{location.pathname + location.search + location.hash}</output>
    <button onClick={() => navigate(-1)}>Test back</button>
    <button onClick={() => navigate('/polls/' + otherPollId)}>Test other poll</button>
    <button onClick={() => navigate('/polls/' + pollId + '#share=' + token)}>Test new private link</button>
  </div>
}
function app(path = '/polls', services = createServices(), captured: CapturedShare = null) {
  services.queryClient.setDefaultOptions({ queries: { retry: false }, mutations: { retry: false } })
  return { services, ...render(<StrictMode><Providers services={services}>
    <MemoryRouter initialEntries={[path]}><App captured={captured} /><LocationProbe /></MemoryRouter>
  </Providers></StrictMode>) }
}
const route = () => screen.getByLabelText('Current route').textContent || ''
function shareResponse(poll: PollDetail = { ...publicPoll, visibility: 'private' }) {
  return json({ poll, share: { poll_id: poll.id, header: 'X-Poll-Share' } })
}
const detailPath = '/api/v2/polls/' + pollId + '/'

describe('discovery and home', () => {
  it('renders real data without invented counts, identity or engagement', async () => {
    const fetcher = backend()
    app()
    expect(await screen.findByRole('link', { name: publicPoll.question })).toHaveAttribute('href', '/polls/' + pollId)
    expect(screen.getByText('1 public poll found')).toBeInTheDocument()
    expect(screen.getByText('Community', { selector: 'span.metadata' })).toBeInTheDocument()
    expect(screen.getByText('Single choice')).toBeInTheDocument()
    expect(screen.queryByText(/participants|selections cast/i)).not.toBeInTheDocument()
    expect(fetcher.mock.calls.some(([path]) => String(path).includes('/results/'))).toBe(false)
  })
  it('hydrates URL filters and paginates without following external response URLs', async () => {
    const fetcher = backend(path => path.startsWith('/api/v2/polls/?') ? json(page([publicPoll], 41, null, 'https://untrusted.invalid/previous')) : undefined)
    app('/polls?q=Tea+%2F+coffee&category=' + category.id + '&sort=oldest&status=closed&page=3')
    await screen.findByRole('link', { name: publicPoll.question })
    expect(screen.getByLabelText('Search polls')).toHaveValue('Tea / coffee')
    expect(screen.getByLabelText('Category')).toHaveValue(category.id)
    expect(screen.getByLabelText('Sort by')).toHaveValue('oldest')
    expect(screen.getByLabelText('Status')).toHaveValue('closed')
    expect(fetcher.mock.calls.some(([path]) => path === '/api/v2/polls/?q=Tea+%2F+coffee&category=' + category.id + '&page=3&sort=oldest&status=closed')).toBe(true)
    await userEvent.click(screen.getByRole('button', { name: 'Previous page' }))
    await waitFor(() => expect(route()).toContain('page=2'))
    expect(fetcher.mock.calls.every(([path]) => String(path).startsWith('/api/v2/'))).toBe(true)
  })
  it('searches explicitly, resets pagination, changes filters and supports back navigation', async () => {
    backend()
    app('/polls?page=2&sort=oldest')
    const user = userEvent.setup()
    await screen.findByRole('option', { name: 'Community' })
    await user.type(screen.getByLabelText('Search polls'), 'Tea')
    expect(route()).not.toContain('q=')
    await user.click(screen.getByRole('button', { name: 'Search' }))
    expect(route()).toContain('q=Tea')
    expect(screen.getByRole('heading', { name: 'Public polls' })).toHaveFocus()
    expect(route()).toContain('page=1')
    await user.selectOptions(screen.getByLabelText('Sort by'), 'closing_soon')
    expect(route()).toContain('sort=closing_soon')
    await user.click(screen.getByRole('button', { name: 'Test back' }))
    await waitFor(() => expect(screen.getByLabelText('Sort by')).toHaveValue('oldest'))
    await user.selectOptions(screen.getByLabelText('Category'), category.id)
    await user.selectOptions(screen.getByLabelText('Status'), 'published')
    expect(route()).toContain('category=' + category.id)
    expect(route()).toContain('status=published')
    await user.click(screen.getByRole('link', { name: 'Clear filters' }))
    expect(route()).toBe('/polls')
    expect(screen.getByLabelText('Search polls')).toHaveValue('')
    await user.type(screen.getByLabelText('Search polls'), 'Unsubmitted search')
    await user.click(screen.getByRole('link', { name: 'Clear filters' }))
    expect(screen.getByLabelText('Search polls')).toHaveValue('')
  })
  it('paginates category choices using local page numbers', async () => {
    const nextCategory = { ...category, id: otherPollId, name: 'Science' }
    const fetcher = backend(path => path.startsWith('/api/v2/categories/') ? json(path.endsWith('page=2')
      ? page([nextCategory], 21, null, 'https://untrusted.invalid/previous')
      : page([category], 21, 'https://untrusted.invalid/next')) : undefined)
    app()
    await userEvent.click(await screen.findByRole('button', { name: 'More categories' }))
    await screen.findByRole('option', { name: 'Science' })
    expect(fetcher.mock.calls.some(([path]) => path === '/api/v2/categories/?page=2')).toBe(true)
    expect(fetcher.mock.calls.every(([path]) => !String(path).includes('untrusted'))).toBe(true)
  })
  it('shows loading and empty states', async () => {
    const pending = deferred<Response>()
    backend(path => path.startsWith('/api/v2/polls/') ? pending.promise.then(response => response.clone()) : undefined)
    app()
    expect(screen.getByText('Loading public polls…')).toBeInTheDocument()
    await act(async () => pending.resolve(json(page([]))))
    expect(await screen.findByRole('heading', { name: 'No polls found' })).toBeInTheDocument()
    expect(screen.getByText('0 public polls found')).toBeInTheDocument()
  })
  it('retries service errors and keeps search available during category failure', async () => {
    let failed = true
    backend(path => path.startsWith('/api/v2/categories/') || (path.startsWith('/api/v2/polls/') && failed) ? failure(503) : undefined)
    app()
    const button = await screen.findByRole('button', { name: 'Retry polls' })
    failed = false
    await userEvent.click(button)
    expect(await screen.findByRole('link', { name: publicPoll.question })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry categories' })).toBeInTheDocument()
    expect(screen.getByRole('search')).toBeInTheDocument()
  })
  it('recovers an out-of-range page', async () => {
    backend(path => path.includes('page=99') ? failure(404) : undefined)
    app('/polls?page=99')
    await userEvent.click(await screen.findByRole('button', { name: 'Go to first page' }))
    await waitFor(() => expect(route()).toContain('page=1'))
    expect(await screen.findByRole('link', { name: publicPoll.question })).toBeInTheDocument()
  })
  it('cancels obsolete searches and ignores late data', async () => {
    const slow = deferred<Response>()
    let signal: AbortSignal | null | undefined
    backend((path, init) => {
      if (path.includes('q=slow')) { signal = init.signal; return slow.promise.then(response => response.clone()) }
      if (path.includes('q=fast')) return json(page([{ ...publicPoll, question: 'Current question?' }]))
      return undefined
    })
    app('/polls?q=slow')
    await waitFor(() => expect(signal).toBeDefined())
    const user = userEvent.setup()
    await user.clear(screen.getByLabelText('Search polls'))
    await user.type(screen.getByLabelText('Search polls'), 'fast')
    await user.click(screen.getByRole('button', { name: 'Search' }))
    expect(await screen.findByRole('link', { name: 'Current question?' })).toBeInTheDocument()
    expect(signal?.aborted).toBe(true)
    await act(async () => slow.resolve(json(page([{ ...publicPoll, question: 'Obsolete question?' }]))))
    expect(screen.queryByText('Obsolete question?')).not.toBeInTheDocument()
  })
  it('supports keyboard pagination and moves focus to the results heading', async () => {
    backend(path => path.startsWith('/api/v2/polls/?') ? json(path.includes('page=2')
      ? page([publicPoll], 21, null, 'previous') : page([publicPoll], 21, 'next')) : undefined)
    app()
    const next = await screen.findByRole('button', { name: 'Next page' })
    await waitFor(() => expect(next).toBeEnabled())
    expect(screen.getByRole('button', { name: 'Previous page' })).toBeDisabled()
    next.focus()
    await userEvent.keyboard('{Enter}')
    await waitFor(() => expect(route()).toContain('page=2'))
    expect(screen.getByRole('heading', { name: 'Public polls' })).toHaveFocus()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Next page' })).toBeDisabled())
  })
  it('normalizes unsupported URL parameters and bounds search length', () => {
    expect(filtersFromUrl(new URLSearchParams('page=-1&sort=bad&category=bad&status=draft'))).toEqual({ page: 1, sort: 'newest' })
    expect(filtersFromUrl(new URLSearchParams({ q: 'x'.repeat(250), page: 'Infinity' })).q).toHaveLength(200)
  })
  it('shows actual recent polls with honest guest calls to action', async () => {
    backend()
    app('/')
    expect(await screen.findByRole('link', { name: publicPoll.question })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Browse polls/ })).toHaveAttribute('href', '/polls')
    expect(screen.queryByText(/testimonials|10,000|engagement/i)).not.toBeInTheDocument()
  })
  it('shows honest home empty and error states', async () => {
    backend(path => path.startsWith('/api/v2/polls/') ? json(page([])) : undefined)
    const first = app('/')
    expect(await screen.findByRole('heading', { name: 'The next question could be yours.' })).toBeInTheDocument()
    first.unmount()
    backend(path => path.startsWith('/api/v2/polls/') ? failure(503) : undefined)
    app('/')
    expect(await screen.findByRole('button', { name: 'Retry recent polls' })).toBeInTheDocument()
  })
  it('passes discovery semantic accessibility checks', async () => {
    backend()
    app()
    await screen.findByRole('link', { name: publicPoll.question })
    document.documentElement.lang = 'en'
    const result = await axe.run(document.body, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'] }, rules: { 'color-contrast': { enabled: false } } })
    expect(result.violations.map(item => item.id)).toEqual([])
  })
})

describe('poll detail', () => {
  it.each([
    ['draft', null, 'This draft is visible only'],
    ['published', null, 'Sign in to participate when voting is available.'],
    ['closed', null, 'Voting is closed.'],
    ['archived', null, 'permanently read-only'],
    ['published', '2001-01-01T00:00:00Z', 'Voting is closed.'],
    ['closed', '2001-01-01T00:00:00Z', 'Voting is closed.'],
  ] as const)('renders lifecycle %s (%s)', async (status, expires_at, message) => {
    backend(path => {
      if (status === 'draft' && path.endsWith('/login/')) return json(sessionData())
      return path === detailPath ? json({ ...publicPoll, status, expires_at }) : undefined
    })
    const services = createServices()
    if (status === 'draft') await services.session.login({ email: alice.email, password: 'fixture' })
    app('/polls/' + pollId, services)
    expect(await screen.findByRole('heading', { name: publicPoll.question })).toBeInTheDocument()
    if (status === 'draft') expect(screen.getByText('Created by you')).toBeInTheDocument()
    expect(screen.getByText(message, { exact: false })).toBeInTheDocument()
    expect(screen.getByText('Morning')).toBeInTheDocument()
    expect(screen.queryByRole('radio')).not.toBeInTheDocument()
  })
  it.each(['immediate', 'after_voting', 'after_closing'] as const)('never fetches or displays counters under %s', async results_visibility => {
    const fetcher = backend(path => path === detailPath ? json({ ...publicPoll, results_visibility,
      options: [{ id: 'option-fixture', option_text: 'Morning', votes_count: 92813 }], total_participants: 76329 }) : undefined)
    app('/polls/' + pollId)
    await screen.findByRole('heading', { name: publicPoll.question })
    expect(document.body.textContent).not.toMatch(/92813|76329/)
    expect(fetcher.mock.calls.some(([path]) => String(path).includes('/results/'))).toBe(false)
    if (results_visibility === 'after_voting') expect(screen.getByText(/participation remains required after closing/)).toBeInTheDocument()
    if (results_visibility === 'after_closing') expect(screen.getByText(/hidden again if reopened/)).toBeInTheDocument()
  })
  it('shows multi-choice limits without actionable voting controls', async () => {
    backend(path => path === detailPath ? json({ ...publicPoll, voting_mode: 'multiple', min_selections: 2, max_selections: 3 }) : undefined)
    app('/polls/' + pollId)
    expect(await screen.findByText('Multiple choice · 2–3 selections.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /submit|vote/i })).not.toBeInTheDocument()
  })
  it('authorizes creator detail requests with a bearer token and shows supported workspace navigation', async () => {
    backend((path, init) => {
      if (path.endsWith('/login/')) return json(sessionData())
      if (path === detailPath) {
        expect(new Headers(init.headers).get('Authorization')).toBe('Bearer test-access-one')
        return json(publicPoll)
      }
      return undefined
    })
    const services = createServices()
    await services.session.login({ email: alice.email, password: 'fixture-password' })
    app('/polls/' + pollId, services)
    expect(await screen.findByText('Created by you')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'My polls workspace' })).toHaveAttribute('href', '/my-polls')
    expect(screen.queryByRole('link', { name: 'Sign in to participate' })).not.toBeInTheDocument()
  })
  it('preserves a safe guest sign-in return path', async () => {
    backend()
    app('/polls/' + pollId)
    expect(await screen.findByRole('link', { name: 'Sign in to participate' })).toHaveAttribute('href', '/login?returnTo=' + encodeURIComponent('/polls/' + pollId))
  })
  it.each([403, 404])('does not disclose hidden/missing resources (%s)', async status => {
    backend(path => path === detailPath ? failure(status) : undefined)
    app('/polls/' + pollId)
    await screen.findByRole('heading', { name: "We couldn't open this poll." })
    expect(screen.queryByText(publicPoll.question)).not.toBeInTheDocument()
  })
  it('shows loading, service errors and retry', async () => {
    const pending = deferred<Response>()
    let first = true
    backend(path => path === detailPath && first ? pending.promise.then(response => response.clone()) : undefined)
    app('/polls/' + pollId)
    expect(screen.getByText('Loading poll…')).toBeInTheDocument()
    await act(async () => pending.resolve(failure(503)))
    first = false
    await userEvent.click(await screen.findByRole('button', { name: 'Retry poll' }))
    await screen.findByRole('heading', { name: publicPoll.question })
  })
  it('does not send a malformed poll ID', async () => {
    const fetcher = backend()
    app('/polls/not-a-uuid')
    await screen.findByRole('heading', { name: 'This page isn’t here.' })
    expect(fetcher.mock.calls.some(([path]) => String(path).includes('not-a-uuid'))).toBe(false)
  })
  it('updates expiration while the detail stays open', async () => {
    backend(path => path === detailPath ? json({ ...publicPoll, expires_at: new Date(Date.now() + 10_000).toISOString() }) : undefined)
    vi.useFakeTimers()
    try {
      app('/polls/' + pollId)
      await act(async () => { await vi.advanceTimersByTimeAsync(100) })
      expect(screen.getByRole('heading', { name: publicPoll.question })).toBeInTheDocument()
      await act(async () => { await vi.advanceTimersByTimeAsync(30_000) })
      expect(screen.getByText('Expired')).toBeInTheDocument()
      expect(screen.getByText('Voting is closed.', { exact: false })).toBeInTheDocument()
    } finally { vi.useRealTimers() }
  })
  it('passes detail semantic accessibility checks with readable options', async () => {
    backend()
    app('/polls/' + pollId)
    await screen.findByRole('heading', { name: publicPoll.question })
    document.documentElement.lang = 'en'
    const result = await axe.run(document.body, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'] }, rules: { 'color-contrast': { enabled: false } } })
    expect(result.violations.map(item => item.id)).toEqual([])
    expect(within(screen.getByRole('list')).getAllByRole('listitem')).toHaveLength(2)
  })
})

describe('private reading and cache isolation', () => {
  it('strips a direct fragment before detail, scopes headers and never persists or caches credentials', async () => {
    window.history.replaceState({}, '', '/polls/' + pollId + '#share=' + token)
    const captured = capturePrivateShare(window)
    const write = vi.spyOn(Storage.prototype, 'setItem')
    const fetcher = backend((path, init) => {
      expect(window.location.hash).toBe('')
      if (path === '/api/v2/shares/resolve/') return shareResponse()
      if (path === detailPath) {
        expect(new Headers(init.headers).get('X-Poll-Share')).toBe(token)
        return json({ ...publicPoll, visibility: 'private' })
      }
      expect(new Headers(init.headers).has('X-Poll-Share')).toBe(false)
      return undefined
    })
    const { services } = app('/polls/' + pollId, createServices(), captured)
    await screen.findByRole('heading', { name: publicPoll.question })
    expect(screen.getByText(/private link provides read-only access/i)).toBeInTheDocument()
    expect(write).not.toHaveBeenCalled()
    expect(JSON.stringify(services.queryClient.getQueryCache().getAll().map(query => [query.queryKey, query.state.data]))).not.toContain(token)
    expect(fetcher.mock.calls.every(([path]) => !String(path).includes(token))).toBe(true)
  })
  it('supports root links and subsequent in-app fragment navigation', async () => {
    backend((path, init) => {
      if (path === '/api/v2/shares/resolve/') return shareResponse()
      if (path === detailPath && new Headers(init.headers).has('X-Poll-Share')) return json({ ...publicPoll, visibility: 'private' })
      return undefined
    })
    app('/', createServices(), { token, expectedPoll: null })
    await screen.findByRole('heading', { name: publicPoll.question })
    await waitFor(() => expect(route()).toBe('/polls/' + pollId))
    await userEvent.click(screen.getByRole('link', { name: 'Explore polls' }))
    await userEvent.click(screen.getByRole('button', { name: 'Test new private link' }))
    await screen.findByRole('heading', { name: publicPoll.question })
    expect(route()).not.toContain('#')
  })
  it.each([400, 404, 503])('shows generic resolution failure without diagnostics (%s)', async status => {
    backend(path => path === '/api/v2/shares/resolve/' ? failure(status, { detail: token }) : undefined)
    app('/polls/' + pollId, createServices(), { token, expectedPoll: pollId })
    await screen.findByRole('heading', { name: "We couldn't open this poll." })
    expect(document.body.textContent).not.toContain(token)
    expect(screen.queryByText(publicPoll.question)).not.toBeInTheDocument()
  })
  it('rejects invalid fragments without a resolver request', async () => {
    const fetcher = backend()
    app('/polls/' + pollId + '#share=invalid')
    await screen.findByRole('heading', { name: "We couldn't open this poll." })
    expect(fetcher.mock.calls.some(([path]) => String(path).includes('shares/resolve'))).toBe(false)
    expect(window.location.hash).toBe('')
  })
  it('never forwards a share header to another poll or discovery', async () => {
    const fetcher = backend((path, init) => {
      if (path === '/api/v2/shares/resolve/') return shareResponse()
      if (path === detailPath) return json({ ...publicPoll, visibility: 'private' })
      if (path === '/api/v2/polls/' + otherPollId + '/') {
        expect(new Headers(init.headers).has('X-Poll-Share')).toBe(false)
        return failure(404)
      }
      return undefined
    })
    app('/polls/' + pollId, createServices(), { token, expectedPoll: pollId })
    await screen.findByRole('heading', { name: publicPoll.question })
    await userEvent.click(screen.getByRole('button', { name: 'Test other poll' }))
    await screen.findByRole('heading', { name: "We couldn't open this poll." })
    for (const [path, init] of fetcher.mock.calls) {
      if (path !== detailPath) expect(new Headers(init?.headers).has('X-Poll-Share')).toBe(false)
    }
  })
  it('clears private queries on explicit end-access and offers reopen guidance', async () => {
    backend((path, init) => {
      if (path === '/api/v2/shares/resolve/') return shareResponse()
      if (path === detailPath) return new Headers(init.headers).has('X-Poll-Share') ? json({ ...publicPoll, visibility: 'private' }) : failure(404)
      return undefined
    })
    const { services } = app('/polls/' + pollId, createServices(), { token, expectedPoll: pollId })
    await screen.findByRole('heading', { name: publicPoll.question })
    await userEvent.click(screen.getByRole('button', { name: 'End private access' }))
    await screen.findByRole('heading', { name: "We couldn't open this poll." })
    expect(services.shares.has(pollId)).toBe(false)
    expect(JSON.stringify(services.queryClient.getQueryCache().getAll().map(query => query.state.data))).not.toContain(publicPoll.question)
  })
  it('discards stale private results when the server revokes access', async () => {
    let revoked = false
    backend(path => {
      if (path === '/api/v2/shares/resolve/') return shareResponse()
      if (path === detailPath) return revoked ? failure(404) : json({ ...publicPoll, visibility: 'private' })
      return undefined
    })
    const { services } = app('/polls/' + pollId, createServices(), { token, expectedPoll: pollId })
    await screen.findByRole('heading', { name: publicPoll.question })
    revoked = true
    await act(async () => services.queryClient.refetchQueries({ queryKey: ['poll', pollId] }))
    await screen.findByRole('heading', { name: "We couldn't open this poll." })
    expect(services.shares.has(pollId)).toBe(false)
    expect(screen.queryByText(publicPoll.question)).not.toBeInTheDocument()
  })
  it('does not reuse private data after a reload without the original link', async () => {
    backend(path => path === detailPath ? failure(404) : undefined)
    app('/polls/' + pollId)
    await screen.findByRole('heading', { name: "We couldn't open this poll." })
    expect(screen.getByText(/reopen the original shared link/i)).toBeInTheDocument()
  })
  it('isolates detail caches across accounts', async () => {
    let identity = alice
    backend(path => {
      if (path.endsWith('/login/')) return json(sessionData('test-access', identity))
      if (path === detailPath) return identity.id === alice.id ? json({ ...publicPoll, visibility: 'private' }) : failure(404)
      return undefined
    })
    const services = createServices()
    await services.session.login({ email: alice.email, password: 'fixture' })
    app('/polls/' + pollId, services)
    await screen.findByText('Created by you')
    identity = bob
    await act(async () => services.session.login({ email: bob.email, password: 'fixture' }))
    await screen.findByRole('heading', { name: "We couldn't open this poll." })
    expect(JSON.stringify(services.queryClient.getQueryCache().getAll().map(query => query.state.data))).not.toContain(publicPoll.question)
  })
  it('cannot revive a pending capability after explicit clearing', async () => {
    const pending = deferred<Response>()
    backend(path => path === '/api/v2/shares/resolve/' ? pending.promise.then(response => response.clone()) : undefined)
    const services = createServices()
    const resolution = services.shares.resolve({ token, expectedPoll: pollId })
    services.shares.clear()
    pending.resolve(shareResponse())
    await expect(resolution).rejects.toMatchObject({ name: 'AbortError' })
    expect(services.shares.has(pollId)).toBe(false)
  })
  it('removes inactive detail queries on navigation', async () => {
    backend()
    const { services } = app('/polls/' + pollId)
    await screen.findByRole('heading', { name: publicPoll.question })
    await userEvent.click(screen.getByRole('link', { name: 'Explore polls' }))
    await waitFor(() => expect(services.queryClient.getQueryCache().findAll({ queryKey: ['poll'] })).toHaveLength(0))
  })
})


describe('share-session race and authorization boundaries', () => {
  it('does not load poll data before private resolution completes', async () => {
    const pending = deferred<Response>()
    const fetcher = backend(path => path === '/api/v2/shares/resolve/' ? pending.promise.then(response => response.clone()) : undefined)
    app('/polls/' + pollId, createServices(), { token, expectedPoll: pollId })
    await waitFor(() => expect(fetcher.mock.calls.some(([path]) => path === '/api/v2/shares/resolve/')).toBe(true))
    expect(screen.getByText('Checking your private link…')).toBeInTheDocument()
    expect(fetcher.mock.calls.some(([path]) => path === detailPath)).toBe(false)
    await act(async () => pending.resolve(shareResponse()))
    await screen.findByRole('heading', { name: publicPoll.question })
  })
  it('discards a late private response after its grant has been ended, even without a caller signal', async () => {
    const pending = deferred<Response>()
    backend(path => path === '/api/v2/shares/resolve/' ? shareResponse() : path === detailPath ? pending.promise : undefined)
    const services = createServices()
    await services.shares.resolve({ token, expectedPoll: pollId })
    const read = services.api.request(detailPath)
    services.shares.revoke(pollId)
    pending.resolve(json({ ...publicPoll, visibility: 'private' }))
    await expect(read).rejects.toMatchObject({ name: 'AbortError' })
  })
  it('evicts old detail caches when a share session is replaced and never keys by token', async () => {
    backend(path => path === '/api/v2/shares/resolve/' ? shareResponse() : undefined)
    const services = createServices()
    await services.shares.resolve({ token, expectedPoll: pollId })
    const oldScope = services.shares.scope(pollId)
    services.queryClient.setQueryData(['poll', pollId, oldScope], { ...publicPoll, visibility: 'private' })
    services.shares.clear()
    await services.shares.resolve({ token: 'z'.repeat(43), expectedPoll: pollId })
    expect(services.shares.scope(pollId)).not.toBe(oldScope)
    expect(services.queryClient.getQueryCache().findAll({ queryKey: ['poll'] })).toHaveLength(0)
    expect(services.shares.scope(pollId)).not.toContain(token)
  })
  it.each(['results/', 'options/' + otherPollId + '/'])('does not mistake a results-policy or missing-option denial for poll revocation (%s)', async suffix => {
    backend(path => path === '/api/v2/shares/resolve/' ? shareResponse() : failure(suffix === 'results/' ? 403 : 404))
    const services = createServices()
    await services.shares.resolve({ token, expectedPoll: pollId })
    await expect(services.api.request(detailPath + suffix)).rejects.toMatchObject({ status: suffix === 'results/' ? 403 : 404 })
    expect(services.shares.has(pollId)).toBe(true)
  })
  it.each(['closed', 'archived'] as const)('keeps authorized private %s polls readable without voting permission', async status => {
    backend(path => path === '/api/v2/shares/resolve/' ? shareResponse({ ...publicPoll, visibility: 'private', status })
      : path === detailPath ? json({ ...publicPoll, visibility: 'private', status }) : undefined)
    app('/polls/' + pollId, createServices(), { token, expectedPoll: pollId })
    await screen.findByRole('heading', { name: publicPoll.question })
    expect(screen.getByText(status === 'archived' ? 'This poll is archived. It is permanently read-only.'
      : 'Voting is closed. New and updated selections are not accepted.')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Sign in to participate' })).not.toBeInTheDocument()
  })
  it('does not start authentication refresh loops when public discovery returns 401', async () => {
    const fetcher = backend(path => path.startsWith('/api/v2/polls/') ? failure(401) : undefined)
    app()
    await screen.findByRole('button', { name: 'Retry polls' })
    expect(fetcher.mock.calls.filter(([path]) => String(path).endsWith('/auth/refresh/'))).toHaveLength(1)
    expect(fetcher.mock.calls.filter(([path]) => String(path).startsWith('/api/v2/polls/')).every(([, init]) => !new Headers(init?.headers).has('Authorization'))).toBe(true)
  })
})

it('does not keep an invalid root share error on later unrelated home visits', async () => {
  backend()
  app('/', createServices(), { invalid: true })
  await screen.findByRole('heading', { name: "We couldn't open this poll." })
  await userEvent.click(screen.getByRole('link', { name: 'Explore public polls' }))
  await screen.findByRole('heading', { name: 'A good question is a great beginning.' })
  await userEvent.click(within(screen.getByRole('navigation', { name: 'Main' })).getByRole('link', { name: 'Home' }))
  expect(await screen.findByRole('heading', { level: 1, name: /Different voices/ })).toBeInTheDocument()
})


it('revokes a denied private grant after an authenticated refresh retry too', async () => {
  backend((path, init) => {
    if (path.endsWith('/login/')) return json(sessionData('old-access'))
    if (path.endsWith('/refresh/')) return json({ access: 'renewed-access', expires_in: 300 })
    if (path.endsWith('/me/')) return json({ user: alice })
    if (path === '/api/v2/shares/resolve/') return shareResponse()
    if (path === detailPath) return failure(new Headers(init.headers).get('Authorization') === 'Bearer old-access' ? 401 : 404)
    return undefined
  })
  const services = createServices()
  await services.session.login({ email: alice.email, password: 'fixture' })
  await services.shares.resolve({ token, expectedPoll: pollId })
  await expect(services.api.request(detailPath, { auth: 'required' })).rejects.toMatchObject({ status: 404 })
  expect(services.shares.has(pollId)).toBe(false)
})
