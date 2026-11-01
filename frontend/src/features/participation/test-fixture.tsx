import { StrictMode } from 'react'
import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import type { Ballot, PollDetail, PollResults } from '../../api/contracts'
import { App } from '../../app/app'
import { Providers } from '../../app/providers'
import { createServices } from '../../app/services'
import type { CapturedShare } from '../sharing/share-vault'
import { alice, bob, failure, json, network, pollId, publicPoll, sessionData } from '../../test/network'

export const morning = publicPoll.options[0]!.id
export const afternoon = publicPoll.options[1]!.id
export const evening = '99999999-9999-4999-8999-999999999999'
export const shareToken = 's'.repeat(43)
export const unsent = (): Ballot => ({ poll_id: pollId, submitted: false, option_ids: [], submitted_at: null, updated_at: null })
export const submitted = (ids = [morning], updated_at: string | null = '2026-01-02T12:00:00Z'): Ballot => ({
  poll_id: pollId, submitted: true, option_ids: ids, submitted_at: '2026-01-01T12:00:00Z', updated_at,
})
export function votingFixture(patch: Partial<PollDetail> = {}, override: (path: string, init: RequestInit) => Response | Promise<Response> | undefined = () => undefined) {
  const state = {
    poll: { ...structuredClone(publicPoll), created_by: bob.id, version: 1, configuration_locked: false, configuration_editable: true,
      options: [...publicPoll.options, { id: evening, option_text: 'Evening' }], ...patch } as PollDetail,
    ballot: unsent(), others: [] as string[][], user: structuredClone(alice),
    writes: 0, reads: 0, posts: [] as string[][], resultReads: 0,
  }
  function aggregate(): PollResults {
    const ballots = [...state.others, ...(state.ballot.submitted ? [state.ballot.option_ids] : [])]
    const selections = ballots.reduce((total, choices) => total + choices.length, 0)
    return { poll_id: pollId, question: state.poll.question, authority: 'bridge', total_participants: ballots.length, total_selections: selections,
      options: state.poll.options.map(option => {
        const count = ballots.filter(choices => choices.includes(option.id)).length
        return { ...option, count, percentage_of_participants: ballots.length ? Math.round(count / ballots.length * 10_000) / 100 : 0,
          percentage_of_selections: selections ? Math.round(count / selections * 10_000) / 100 : 0 }
      }) }
  }
  const fetcher = network((path, init) => {
    const custom = override(path, init)
    if (custom) return custom
    const headers = new Headers(init.headers)
    const authenticated = headers.has('Authorization')
    const owner = authenticated && state.user.id === state.poll.created_by
    const hasShare = headers.get('X-Poll-Share') === shareToken
    const body = init.body ? JSON.parse(String(init.body)) : {}
    if (path.endsWith('/csrf/')) return json({ csrf_token: 'fixture-csrf' })
    if (path.endsWith('/login/') || path.endsWith('/register/')) {
      state.user = body.email === bob.email ? structuredClone(bob) : structuredClone(alice)
      return json(sessionData('h3-access-' + state.user.id, state.user), path.endsWith('/register/') ? 201 : 200)
    }
    if (path.endsWith('/me/')) return json({ user: state.user })
    if (path.endsWith('/refresh/')) return failure(401)
    if (path.endsWith('/logout/')) return json(null, 204)
    if (path.startsWith('/api/v2/categories/')) return json({ count: 0, next: null, previous: null, results: [] })
    if (path.startsWith('/api/v2/polls/?')) return json({ count: 0, next: null, previous: null, results: [] })
    if (path === '/api/v2/shares/resolve/') return json({ poll: state.poll, share: { poll_id: pollId, header: 'X-Poll-Share' } })
    const prefix = '/api/v2/polls/' + pollId + '/'
    if (!path.startsWith(prefix)) return failure(404)
    if ((state.poll.status === 'draft' && !owner) || (state.poll.visibility === 'private' && !owner && !hasShare && !path.endsWith('/ballots/'))) return failure(404)
    if (path === prefix) {
      const poll = structuredClone(state.poll)
      if (!owner) { delete poll.version; delete poll.configuration_locked; delete poll.configuration_editable }
      return json(poll)
    }
    if (path === prefix + 'ballots/') {
      if (!authenticated) return failure(401)
      if (state.poll.visibility === 'private' && !owner) return failure(404)
      if (init.method === 'POST') {
        const ids = body.option_ids as string[]
        if (state.poll.status !== 'published' || (state.poll.expires_at && Date.parse(state.poll.expires_at) <= Date.now())) return failure(400, { poll: ['Poll is not open for voting.'] })
        if (!Array.isArray(ids) || !ids.length || new Set(ids).size !== ids.length || ids.some(id => !state.poll.options.some(option => option.id === id))) return failure(400)
        if (state.poll.voting_mode === 'single' ? ids.length !== 1 : ids.length < state.poll.min_selections || (state.poll.max_selections !== null && ids.length > state.poll.max_selections)) return failure(400)
        state.posts.push([...ids]); state.writes++
        state.ballot = { poll_id: pollId, submitted: true, option_ids: ids,
          submitted_at: state.ballot.submitted_at || '2026-11-01T10:00:00Z', updated_at: new Date(Date.now() + state.writes).toISOString() }
        state.poll.configuration_locked = true
        return json(state.ballot)
      }
      state.reads++
      return json(state.ballot)
    }
    if (path === prefix + 'results/') {
      state.resultReads++
      const closed = state.poll.status === 'closed' || state.poll.status === 'archived' || (!!state.poll.expires_at && Date.parse(state.poll.expires_at) <= Date.now())
      if (!owner && !(state.poll.results_visibility === 'immediate'
        || (state.poll.results_visibility === 'after_voting' && authenticated && state.ballot.submitted)
        || (state.poll.results_visibility === 'after_closing' && closed))) return failure(403)
      return json(aggregate())
    }
    if (path === prefix + 'reopen/') { state.poll.status = 'published'; state.poll.expires_at = body.expires_at; state.poll.version!++; return json(state.poll) }
    return failure(404)
  })
  return { state, fetcher, aggregate }
}
export async function votingApp({ guest = false, services = createServices(), captured = null, path = '/polls/' + pollId }:
  { guest?: boolean; services?: ReturnType<typeof createServices>; captured?: CapturedShare; path?: string } = {}) {
  if (!guest) await services.session.login({ email: alice.email, password: 'fixture-password' })
  services.queryClient.setDefaultOptions({ queries: { retry: false }, mutations: { retry: false } })
  return { services, ...render(<StrictMode><Providers services={services}><MemoryRouter initialEntries={[path]}>
    <App captured={captured} />
  </MemoryRouter></Providers></StrictMode>) }
}
