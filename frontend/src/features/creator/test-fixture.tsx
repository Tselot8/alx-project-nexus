import { StrictMode } from 'react'
import { render } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router'
import type { PollDetail } from '../../api/contracts'
import { App } from '../../app/app'
import { createServices } from '../../app/services'
import { Providers } from '../../app/providers'
import { alice, failure, json, network, pollId, publicPoll, sessionData } from '../../test/network'

export const category = { id: '55555555-5555-4555-8555-555555555555', name: 'Community', description: null }
export const draftPoll = (patch: Partial<PollDetail> = {}): PollDetail => ({
  ...structuredClone(publicPoll), status: 'draft', version: 1, configuration_editable: true, configuration_locked: false, ...patch,
})
export function fixture(patch: Partial<PollDetail> = {}, override: (path: string, init: RequestInit) => Response | Promise<Response> | undefined = () => undefined) {
  const state = { poll: draftPoll(patch) as PollDetail | null, active: false, generation: 1, user: structuredClone(alice) }
  const fetcher = network((path, init) => {
    const custom = override(path, init)
    if (custom) return custom
    const method = init.method || 'GET'
    const body = init.body ? JSON.parse(String(init.body)) : {}
    if (path.endsWith('/csrf/')) return json({ csrf_token: 'fixture-csrf' })
    if (path.endsWith('/login/')) return json(sessionData('fixture-access', state.user))
    if (path.endsWith('/refresh/')) return failure(401)
    if (path.endsWith('/logout/')) return json(null, 204)
    if (path.endsWith('/me/')) {
      if (method === 'PATCH') state.user = { ...state.user, username: body.username, profile: body.profile }
      return json({ user: state.user })
    }
    if (path.endsWith('/password/change/')) return json(null, 204)
    if (path.startsWith('/api/v2/categories/')) return json({ count: 1, next: null, previous: null, results: [category] })
    if (path.startsWith('/api/v2/polls/mine/')) {
      const query = new URL(path, 'http://localhost').searchParams
      const polls = state.poll && (!query.get('status') || state.poll.status === query.get('status')) ? [state.poll] : []
      return json({ count: polls.length, next: null, previous: null, results: polls })
    }
    if (path === '/api/v2/polls/' && method === 'POST') {
      state.poll = draftPoll({ ...body, options: body.options.map((option: { option_text: string }) => ({ ...option, id: crypto.randomUUID() })) })
      return json(state.poll, 201)
    }
    if (path.startsWith('/api/v2/polls/?')) return json({ count: 0, next: null, previous: null, results: [] })
    if (!state.poll || !path.startsWith('/api/v2/polls/' + pollId + '/')) return failure(404)
    const suffix = path.slice(('/api/v2/polls/' + pollId + '/').length)
    if (!suffix) {
      if (method === 'DELETE') { state.poll = null; return json(null, 204) }
      if (method === 'PATCH') state.poll = { ...state.poll, ...body, version: state.poll.version! + 1 }
      return json(state.poll)
    }
    if (['publish/', 'close/', 'reopen/', 'archive/'].includes(suffix)) {
      const status = suffix === 'publish/' || suffix === 'reopen/' ? 'published' : suffix === 'close/' ? 'closed' : 'archived'
      state.poll = { ...state.poll, ...body, status, version: state.poll.version! + 1 }
      return json(state.poll)
    }
    if (suffix === 'share/' || suffix === 'share/regenerate/') {
      if (method === 'GET') return json({ poll_id: pollId, active: state.active, generation: state.generation })
      state.generation++
      state.active = method !== 'DELETE'
      return method === 'DELETE' ? json(null, 204) : json({ poll_id: pollId, generation: state.generation, token: 't'.repeat(43) }, 201)
    }
    if (suffix.startsWith('options/')) {
      const id = suffix.split('/')[1]
      if (method === 'POST') {
        const option = { id: crypto.randomUUID(), option_text: body.option_text }
        state.poll.options.push(option); state.poll.version!++
        return json(option, 201)
      }
      if (method === 'DELETE') { state.poll.options = state.poll.options.filter(option => option.id !== id); state.poll.version!++; return json(null, 204) }
      const option = state.poll.options.find(option => option.id === id)
      if (!option) return failure(404)
      option.option_text = body.option_text; state.poll.version!++
      return json(option)
    }
    return failure(404)
  })
  return { state, fetcher }
}
function LocationProbe() {
  const location = useLocation()
  return <output aria-label="Current route">{location.pathname + location.search}</output>
}
export async function authenticatedApp(path: string, services = createServices()) {
  await services.session.login({ email: alice.email, password: 'fixture-password' })
  services.queryClient.setDefaultOptions({ queries: { retry: false }, mutations: { retry: false } })
  return { services, ...render(<StrictMode><Providers services={services}><MemoryRouter initialEntries={[path]}>
    <App /><LocationProbe />
  </MemoryRouter></Providers></StrictMode>) }
}
export const writes = (fetcher: ReturnType<typeof network>) => fetcher.mock.calls.filter(([, init]) => init?.method && init.method !== 'GET')
