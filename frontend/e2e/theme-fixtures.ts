import type { BrowserContext } from '@playwright/test'
import type { Ballot, PollDetail, PollResults } from '../src/api/contracts'

export const themePollId = '33333333-3333-4333-8333-333333333333'
const user = { id: '11111111-1111-4111-8111-111111111111', username: 'LocalReader', email: 'reader@example.invalid', profile: { bio: 'Local visual fixture', location: 'A fictional town' } }
export const themePoll: PollDetail = {
  id: themePollId, question: 'What would make your next weekend a good one?',
  description: 'A little space to recharge looks different for everyone. Choose up to two ways you would spend a free afternoon.',
  category: '55555555-5555-4555-8555-555555555555', created_by: '22222222-2222-4222-8222-222222222222',
  visibility: 'public', voting_mode: 'multiple', status: 'published', expires_at: '2027-06-01T18:00:00Z',
  created_at: '2026-11-01T12:00:00Z', updated_at: '2026-11-01T12:00:00Z', version: 1,
  results_visibility: 'immediate', min_selections: 1, max_selections: 2, configuration_locked: false, configuration_editable: true,
  options: ['A long walk outdoors', 'A good book and a quiet corner', 'Cooking something new', 'Catching up with friends'].map((option_text, i) => ({ id: `${i + 6}7777777-7777-4777-8777-777777777777`, option_text })),
}
export type ThemeFixture = { authenticated?: boolean; submitted?: boolean; owner?: boolean; empty?: boolean; error?: boolean; status?: PollDetail['status']; single?: boolean }
export async function themeFixtures(context: BrowserContext, base: string, fixture: ThemeFixture = {}) {
  let authenticated = fixture.authenticated === true
  let ballot: Ballot = { poll_id: themePollId, submitted: fixture.submitted === true, option_ids: fixture.submitted ? [themePoll.options[0]!.id] : [],
    submitted_at: fixture.submitted ? '2026-11-20T12:00:00Z' : null, updated_at: fixture.submitted ? '2026-11-20T12:00:00Z' : null }
  const poll = { ...themePoll, ...(fixture.owner ? { created_by: user.id } : {}), ...(fixture.status ? { status: fixture.status } : {}), ...(fixture.single ? { voting_mode: 'single' as const, max_selections: null } : {}) }
  const page = <T,>(results: T[]) => ({ count: results.length, next: null, previous: null, results })
  const reject = (status: number) => ({ status, json: { error: { code: 'request_failed', details: { detail: 'Local fixture rejection.' } } } })
  await context.route('**/*', async route => {
    const url = new URL(route.request().url())
    if (url.origin !== base) { await route.abort(); return }
    if (!url.pathname.startsWith('/api/')) { await route.continue(); return }
    const path = url.pathname
    const method = route.request().method()
    if (path.endsWith('/csrf/')) { await route.fulfill({ json: { csrf_token: 'local-visual-csrf' } }); return }
    if (path.endsWith('/refresh/')) { await route.fulfill(authenticated ? { json: { access: 'local-visual-access', expires_in: 300 } } : reject(401)); return }
    if (path.endsWith('/login/') || path.endsWith('/register/')) {
      authenticated = true
      await route.fulfill({ status: path.endsWith('/register/') ? 201 : 200, json: { user, access: 'local-visual-access', expires_in: 300, csrf_token: 'local-visual-csrf' } }); return
    }
    if (path.endsWith('/logout/')) { authenticated = false; await route.fulfill({ json: { detail: 'Signed out.' } }); return }
    if (path.endsWith('/me/')) { await route.fulfill({ json: { user } }); return }
    if (fixture.error && !path.includes('/auth/')) { await route.fulfill(reject(503)); return }
    if (path === '/api/v2/categories/') { await route.fulfill({ json: page([{ id: themePoll.category, name: 'Community', description: null }]) }); return }
    if (path === '/api/v2/polls/' || path === '/api/v2/polls/mine/') {
      await route.fulfill({ json: page(fixture.empty ? [] : [poll, { ...poll, id: '44444444-4444-4444-8444-444444444444', question: 'When do your best ideas arrive?', description: 'There is more than one good time to find a fresh perspective.', voting_mode: 'single' }, { ...poll, id: '55555555-5555-4555-8555-555555555555', question: 'What makes a neighborhood feel like home?', status: 'closed' }]) }); return
    }
    if (path === '/api/v2/polls/' + themePollId + '/') { await route.fulfill({ json: poll }); return }
    if (path.endsWith('/ballots/')) {
      if (method === 'POST') {
        const data = route.request().postDataJSON() as { option_ids: string[] }
        ballot = { ...ballot, option_ids: data.option_ids, submitted: true, submitted_at: ballot.submitted_at || '2026-11-20T12:00:00Z', updated_at: '2026-11-20T12:01:00Z' }
      }
      await route.fulfill({ json: ballot }); return
    }
    if (path.endsWith('/results/')) {
      const counts = fixture.single ? [2, 1, 0, 0] : [2, 2, 1, 0]
      const results: PollResults = { poll_id: themePollId, question: poll.question, authority: 'bridge', total_participants: 3, total_selections: fixture.single ? 3 : 5,
        options: poll.options.map((option, i) => ({ ...option, count: counts[i]!, percentage_of_participants: Math.round(counts[i]! / 3 * 10000) / 100, percentage_of_selections: Math.round(counts[i]! / (fixture.single ? 3 : 5) * 10000) / 100 })) }
      await route.fulfill({ json: results }); return
    }
    if (path.endsWith('/share/')) { await route.fulfill({ json: { poll_id: themePollId, active: false, generation: null } }); return }
    await route.fulfill(reject(404))
  })
}
