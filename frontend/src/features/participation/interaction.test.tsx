import { act, fireEvent, renderHook, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import axe from 'axe-core'
import { alice, bob, deferred, failure, json, pollId } from '../../test/network'
import { creatorCommands } from '../creator/api'
import { useNow } from '../polls/presentation'
import { pollOpen } from './api'
import { afternoon, evening, morning, shareToken, submitted, unsent, votingApp, votingFixture } from './test-fixture'

const prefix = '/api/v2/polls/' + pollId + '/'
const ballotUrl = prefix + 'ballots/'
const resultsUrl = prefix + 'results/'
async function vote(name = 'Morning') {
  await userEvent.click(await screen.findByRole('radio', { name: new RegExp(name) }))
  await userEvent.click(screen.getByRole('button', { name: 'Submit vote' }))
  await screen.findByText('Your vote was saved.')
}
async function table() { return screen.findByRole('table') }
describe('complete-set ballot interactions', () => {
  it('submits one single-choice ballot and updates only from the server receipt', async () => {
    const { state, fetcher } = votingFixture()
    const { services } = await votingApp()
    await vote()
    expect(state.posts).toEqual([[morning]])
    expect(await screen.findByText('Saved ballot on file')).toBeInTheDocument()
    expect(await table()).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Update vote' })).toBeDisabled())
    const post = fetcher.mock.calls.find(([path, init]) => path === ballotUrl && init?.method === 'POST')!
    expect(JSON.parse(String(post[1]?.body))).toEqual({ option_ids: [morning] })
    expect(new Headers(post[1]?.headers).get('Authorization')).toContain('Bearer h3-access-')
    expect(new Headers(post[1]?.headers).has('X-Poll-Share')).toBe(false)
    expect(services.queryClient.getMutationCache().getAll()).toEqual([])
  })
  it('shows saved selections and replaces the entire single-choice ballot', async () => {
    const { state } = votingFixture()
    state.ballot = submitted([morning], null)
    const first = state.ballot.submitted_at
    await votingApp()
    expect(await screen.findByRole('radio', { name: /Morning/ })).toBeChecked()
    expect(screen.getByRole('button', { name: 'Update vote' })).toBeDisabled()
    await userEvent.click(screen.getByRole('radio', { name: /Afternoon/ }))
    expect(screen.getByText(/Unsaved changes/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Update vote' }))
    await screen.findByText(/Your ballot was updated/)
    expect(state.posts).toEqual([[afternoon]])
    expect(state.ballot.submitted_at).toBe(first)
    await waitFor(() => expect(screen.getByRole('radio', { name: /Afternoon/ })).toBeChecked())
  })
  it('uses native keyboard radio navigation and announces validation', async () => {
    votingFixture()
    await votingApp()
    const first = await screen.findByRole('radio', { name: /Morning/ })
    first.focus()
    await userEvent.keyboard(' {ArrowRight}')
    expect(screen.getByRole('radio', { name: /Afternoon/ })).toBeChecked()
    expect(screen.getByText('1 selected · Unsaved changes')).toBeInTheDocument()
  })
  it('rejects empty initial choices without writing', async () => {
    const { state } = votingFixture()
    await votingApp()
    await userEvent.click(await screen.findByRole('button', { name: 'Submit vote' }))
    expect(screen.getAllByText('Choose at least one option. A submitted ballot cannot be withdrawn.').length).toBeGreaterThan(0)
    expect(state.writes).toBe(0)
    expect(screen.getByRole('group', { name: 'Choose one answer' })).toHaveAccessibleDescription(/Choose at least one option/)
  })
  it('submits a multiple-choice set with minimum/maximum guidance', async () => {
    const { state } = votingFixture({ voting_mode: 'multiple', min_selections: 2, max_selections: 2 })
    await votingApp()
    await userEvent.click(await screen.findByRole('checkbox', { name: /Morning/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Submit vote' }))
    expect(screen.getAllByText('Choose 2–2 options.').length).toBeGreaterThan(0)
    expect(state.writes).toBe(0)
    await userEvent.click(screen.getByRole('checkbox', { name: /Afternoon/ }))
    expect(screen.getByRole('checkbox', { name: /Evening/ })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: 'Submit vote' }))
    await screen.findByText('Your vote was saved.')
    expect(state.posts).toEqual([[morning, afternoon]])
  })
  it('supports unbounded multiple choice and sends only the chosen set', async () => {
    const { state } = votingFixture({ voting_mode: 'multiple', min_selections: 1, max_selections: null })
    await votingApp()
    for (const label of ['Morning', 'Afternoon', 'Evening']) await userEvent.click(await screen.findByRole('checkbox', { name: new RegExp(label) }))
    await userEvent.click(screen.getByRole('button', { name: 'Submit vote' }))
    await screen.findByText('Your vote was saved.')
    expect(state.posts).toEqual([[morning, afternoon, evening]])
  })
  it('does not withdraw a submitted ballot when every checkbox is unchecked', async () => {
    const { state } = votingFixture({ voting_mode: 'multiple', min_selections: 1, max_selections: 3 })
    state.ballot = submitted([morning, afternoon])
    await votingApp()
    await userEvent.click(await screen.findByRole('checkbox', { name: /Morning/ }))
    await userEvent.click(screen.getByRole('checkbox', { name: /Afternoon/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Update vote' }))
    expect(state.writes).toBe(0)
    expect(state.ballot.option_ids).toEqual([morning, afternoon])
    expect(screen.getAllByText(/cannot be withdrawn/).length).toBeGreaterThan(0)
    await userEvent.click(screen.getByRole('button', { name: 'Reload saved selections' }))
    await screen.findByText('Saved selections reloaded. Review them before making changes.')
    expect(screen.getByRole('checkbox', { name: /Morning/ })).toBeChecked()
  })
  it('replaces rather than incrementally adds multiple-choice selections', async () => {
    const { state } = votingFixture({ voting_mode: 'multiple', min_selections: 1, max_selections: 2 })
    state.ballot = submitted([morning, afternoon])
    await votingApp()
    await userEvent.click(await screen.findByRole('checkbox', { name: /Morning/ }))
    await userEvent.click(screen.getByRole('checkbox', { name: /Evening/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Update vote' }))
    await screen.findByText(/Your ballot was updated/)
    expect(state.posts).toEqual([[afternoon, evening]])
  })
  it('prevents duplicate clicks and does not optimistically change aggregates', async () => {
    const pending = deferred<Response>()
    const { fetcher } = votingFixture({}, (path, init) => path === ballotUrl && init.method === 'POST' ? pending.promise : undefined)
    await votingApp()
    await table()
    await userEvent.click(await screen.findByRole('radio', { name: /Morning/ }))
    const submit = screen.getByRole('button', { name: 'Submit vote' })
    fireEvent.click(submit); fireEvent.click(submit)
    await waitFor(() => expect(submit).toBeDisabled())
    expect(fetcher.mock.calls.filter(([path, init]) => path === ballotUrl && init?.method === 'POST')).toHaveLength(1)
    expect(screen.getByText('No votes yet.')).toBeInTheDocument()
    await act(async () => pending.resolve(json(submitted())))
    await screen.findByText('Your vote was saved.')
  })
  it.each(['closed', 'archived'] as const)('shows a saved ballot read-only when %s', async status => {
    const { state } = votingFixture({ status })
    state.ballot = submitted()
    await votingApp()
    expect(await screen.findByRole('radio', { name: /Morning/ })).toBeChecked()
    expect(screen.getByRole('radio', { name: /Morning/ })).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Update vote' })).not.toBeInTheDocument()
    expect(state.writes).toBe(0)
  })
  it('does not offer voting for an already expired poll', async () => {
    const { state } = votingFixture({ expires_at: '2001-01-01T00:00:00Z' })
    await votingApp()
    expect(await screen.findByRole('radio', { name: /Morning/ })).toBeDisabled()
    expect(screen.getByText(/Voting is closed/)).toBeInTheDocument()
    expect(state.writes).toBe(0)
  })
  it('shows creator drafts read-only without requesting a ballot', async () => {
    const { fetcher } = votingFixture({ status: 'draft', created_by: alice.id })
    await votingApp()
    await screen.findByText(/This draft is visible only/)
    expect(screen.queryByRole('radio', { name: /Morning/ })).not.toBeInTheDocument()
    expect(fetcher.mock.calls.some(([path]) => path === ballotUrl)).toBe(false)
  })
  it('blocks editing if a saved ballot contains options missing from the current poll', async () => {
    votingFixture({}, path => path === ballotUrl ? json(submitted(['aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'])) : undefined)
    await votingApp()
    await screen.findByText(/Your saved ballot or the available options changed/)
    expect(screen.getByRole('button', { name: 'Update vote' })).toBeDisabled()
  })
  it('preserves unsaved changes when a background ballot update is detected', async () => {
    const { state } = votingFixture()
    state.ballot = submitted()
    const { services } = await votingApp()
    await userEvent.click(await screen.findByRole('radio', { name: /Afternoon/ }))
    state.ballot = submitted([evening], '2026-11-01T12:00:00Z')
    await act(async () => services.queryClient.refetchQueries({ queryKey: ['ballot'] }))
    await screen.findByText(/Your saved ballot or the available options changed/)
    expect(screen.getByRole('radio', { name: /Afternoon/ })).toBeChecked()
    expect(screen.getByRole('button', { name: 'Update vote' })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: 'Reload saved selections' }))
    await screen.findByText('Saved selections reloaded. Review them before making changes.')
    expect(screen.getByRole('radio', { name: /Evening/ })).toBeChecked()
  })
  it('reconciles an interrupted submission without automatically reposting', async () => {
    const { state, fetcher } = votingFixture({}, (path, init) => {
      if (path === ballotUrl && init.method === 'POST') { state.ballot = submitted([morning]); return failure(503) }
      return undefined
    })
    await votingApp()
    await userEvent.click(await screen.findByRole('radio', { name: /Morning/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Submit vote' }))
    await screen.findByText(/Submission could not be confirmed/)
    expect(screen.queryByText('Your vote was saved.')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Submit vote|Update vote/ })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: 'Reload saved selections' }))
    await screen.findByText('Saved selections reloaded. Review them before making changes.')
    expect(screen.getByText('Saved ballot on file')).toBeInTheDocument()
    expect(fetcher.mock.calls.filter(([path, init]) => path === ballotUrl && init?.method === 'POST')).toHaveLength(1)
  })
  it.each([400, 403, 404, 409])('handles submission failure %s without modifying the saved ballot', async status => {
    const { state } = votingFixture({}, (path, init) => path === ballotUrl && init.method === 'POST' ? failure(status) : undefined)
    await votingApp()
    await userEvent.click(await screen.findByRole('radio', { name: /Morning/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Submit vote' }))
    await screen.findByRole('alert')
    expect(state.ballot.submitted).toBe(false)
    expect(state.writes).toBe(0)
    expect(screen.queryByText('Your vote was saved.')).not.toBeInTheDocument()
  })
  it('retries a saved-ballot read failure before enabling voting', async () => {
    let failed = true
    votingFixture({}, path => path === ballotUrl && failed ? failure(503) : undefined)
    await votingApp()
    const retry = await screen.findByRole('button', { name: 'Retry saved selections' })
    expect(screen.queryByRole('button', { name: 'Submit vote' })).not.toBeInTheDocument()
    failed = false
    await userEvent.click(retry)
    expect(await screen.findByRole('button', { name: 'Submit vote' })).toBeInTheDocument()
  })
  it('passes semantic accessibility checks for voting and aggregate data', async () => {
    votingFixture()
    await votingApp()
    await screen.findByRole('radio', { name: /Morning/ })
    await table()
    document.documentElement.lang = 'en'
    const result = await axe.run(document.body, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'] }, rules: { 'color-contrast': { enabled: false } } })
    expect(result.violations.map(row => row.id)).toEqual([])
  })
})
describe('policy-aware aggregate results and private access', () => {
  it('uses a safe sign-in return and activates participation after login', async () => {
    votingFixture()
    await votingApp({ guest: true })
    const link = await screen.findByRole('link', { name: 'Sign in to participate' })
    expect(link).toHaveAttribute('href', '/login?returnTo=' + encodeURIComponent('/polls/' + pollId))
    await userEvent.click(link)
    fireEvent.change(screen.getByLabelText('Email address'), { target: { value: alice.email } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'fixture-password' } })
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('radio', { name: /Morning/ })).toBeEnabled()
  })
  it('shows authorized zero results and both correct multiple-choice percentage measures', async () => {
    const { state } = votingFixture({ voting_mode: 'multiple' })
    state.others = [[morning, afternoon], [morning]]
    await votingApp({ guest: true })
    const results = await table()
    expect(within(results).getByRole('row', { name: /Morning/ })).toHaveTextContent('2')
    expect(within(results).getByRole('row', { name: /Morning/ })).toHaveTextContent('100%')
    expect(within(results).getByRole('row', { name: /Morning/ })).toHaveTextContent('66.67%')
    expect(screen.getByText(/percentages can add up to more than 100%/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('radio', { name: 'Selections' }))
    expect(screen.getByText(/Percentages add up to about 100%/)).toBeInTheDocument()
    expect(screen.getByText('Results by percentage of selections')).toBeInTheDocument()
  })
  it('shows an honest zero-vote state with numeric zero rows', async () => {
    votingFixture()
    await votingApp({ guest: true })
    await screen.findByText('No votes yet.')
    expect(within(await table()).getByRole('row', { name: /Morning/ })).toHaveTextContent('0%')
  })
  it('does not request after-voting aggregates for guests even after closure', async () => {
    const { state, fetcher } = votingFixture({ results_visibility: 'after_voting', status: 'closed' })
    state.others = [[morning]]
    await votingApp({ guest: true })
    await screen.findByText(/Results are available only after your account has voted/)
    expect(fetcher.mock.calls.some(([path]) => path === resultsUrl || path === ballotUrl)).toBe(false)
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })
  it('unlocks after-voting results only after confirmed participation', async () => {
    votingFixture({ results_visibility: 'after_voting' })
    await votingApp()
    await screen.findByText(/Results are available only after your account has voted/)
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    await vote()
    expect(await table()).toBeInTheDocument()
    expect(screen.getByText('Unique participants')).toBeInTheDocument()
  })
  it('keeps after-voting results restricted for a nonparticipant after closure', async () => {
    const { state } = votingFixture({ results_visibility: 'after_voting', status: 'closed' })
    state.others = [[morning]]
    await votingApp()
    await screen.findByText(/Results are available only after your account has voted/)
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })
  it('allows a prior participant to see after-voting results on an archived poll', async () => {
    const { state } = votingFixture({ results_visibility: 'after_voting', status: 'archived' })
    state.ballot = submitted()
    await votingApp()
    expect(await table()).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Update vote' })).not.toBeInTheDocument()
  })
  it('does not request after-closing results while open and relocks after reopening', async () => {
    const { state } = votingFixture({ results_visibility: 'after_closing', status: 'closed' })
    state.others = [[morning]]
    const { services } = await votingApp({ guest: true })
    await table()
    state.poll.status = 'published'; state.poll.expires_at = '2037-01-01T00:00:00Z'; state.poll.version!++
    await act(async () => services.queryClient.refetchQueries({ queryKey: ['poll'] }))
    await screen.findByText('Results are available after voting closes. Reopening a poll hides them again.')
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    await waitFor(() => expect(services.queryClient.getQueryCache().findAll({ queryKey: ['poll-results'] })).toHaveLength(0))
  })
  it('always permits creators to inspect aggregate results, including a draft', async () => {
    votingFixture({ created_by: alice.id, status: 'draft', results_visibility: 'after_closing' })
    await votingApp()
    expect(await table()).toBeInTheDocument()
    expect(screen.getByText('Created by you')).toBeInTheDocument()
  })
  it('never caches or renders denied diagnostic counts or voter identities', async () => {
    votingFixture({ results_visibility: 'after_voting' }, path => path === resultsUrl ? failure(403, { detail: 'hidden-total-838383', total_participants: 838383, voters: ['private-voter@example.invalid'] }) : undefined)
    const { services } = await votingApp()
    await screen.findByText(/Results are available only after your account has voted/)
    expect(document.body.textContent).not.toMatch(/838383|private-voter/)
    expect(JSON.stringify(services.queryClient.getQueryCache().findAll({ queryKey: ['poll-results'] }).map(query => query.state))).not.toMatch(/838383|private-voter/)
  })
  it('replaces previously authorized aggregates with a count-free denied state on refresh', async () => {
    let denied = false
    const { state } = votingFixture({ results_visibility: 'after_voting' }, path => path === resultsUrl && denied ? failure(403) : undefined)
    state.ballot = submitted()
    const { services } = await votingApp()
    await table()
    denied = true
    await act(async () => services.queryClient.refetchQueries({ queryKey: ['poll-results'] }))
    await screen.findByText(/Results are available only after your account has voted/)
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(services.queryClient.getQueryCache().findAll({ queryKey: ['poll-results'] }).every(query => (query.state.data as { kind: string })?.kind === 'restricted')).toBe(true)
  })
  it('retries results read errors without showing stale counts', async () => {
    let failed = true
    votingFixture({}, path => path === resultsUrl && failed ? failure(503) : undefined)
    await votingApp({ guest: true })
    const retry = await screen.findByRole('button', { name: 'Retry results' })
    failed = false
    await userEvent.click(retry)
    expect(await table()).toBeInTheDocument()
  })
  it('keeps private share access read-only for guests and signed-in non-creators', async () => {
    const { fetcher } = votingFixture({ visibility: 'private' })
    await votingApp({ captured: { token: shareToken, expectedPoll: pollId } })
    await screen.findByText(/Only the creator can vote on private polls/)
    await table()
    expect(screen.queryByRole('radio', { name: /Morning/ })).not.toBeInTheDocument()
    expect(fetcher.mock.calls.some(([path]) => path === ballotUrl)).toBe(false)
    const read = fetcher.mock.calls.find(([path]) => path === resultsUrl)!
    expect(new Headers(read[1]?.headers).get('X-Poll-Share')).toBe(shareToken)
    expect(new Headers(read[1]?.headers).get('Authorization')).toContain('Bearer')
  })
  it('allows the authenticated creator, not the share token, to submit to a private poll', async () => {
    const { fetcher, state } = votingFixture({ visibility: 'private', created_by: alice.id })
    await votingApp({ captured: { token: shareToken, expectedPoll: pollId } })
    await vote()
    expect(state.writes).toBe(1)
    for (const [path, init] of fetcher.mock.calls) if (path === ballotUrl) expect(new Headers(init?.headers).has('X-Poll-Share')).toBe(false)
  })
  it('lets the results endpoint establish historical private participation without granting voting', async () => {
    const { state, fetcher } = votingFixture({ visibility: 'private', results_visibility: 'after_voting' })
    state.ballot = submitted()
    await votingApp({ captured: { token: shareToken, expectedPoll: pollId } })
    await table()
    expect(fetcher.mock.calls.some(([path]) => path === ballotUrl)).toBe(false)
    expect(screen.queryByRole('button', { name: 'Update vote' })).not.toBeInTheDocument()
  })
  it('clears protected ballot/results queries on logout and isolates a new account', async () => {
    const { state } = votingFixture({ results_visibility: 'after_voting', created_by: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa' })
    state.ballot = submitted()
    const { services } = await votingApp()
    await table()
    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    await screen.findByRole('link', { name: 'Sign in to participate' })
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    await waitFor(() => expect(services.queryClient.getQueryCache().findAll({ queryKey: ['ballot'] })).toHaveLength(0))
    state.others = [[morning]]; state.ballot = unsent()
    await act(async () => services.session.login({ email: bob.email, password: 'fixture-password' }))
    expect(await screen.findByRole('radio', { name: /Morning/ })).not.toBeChecked()
    await screen.findByText(/Results are available only after your account has voted/)
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(services.queryClient.getQueryCache().findAll({ queryKey: ['ballot'] }).some(query => query.queryKey.includes(alice.id))).toBe(false)
  })
  it('purges cached aggregates before a creator lifecycle command', async () => {
    votingFixture({ created_by: alice.id, status: 'closed', results_visibility: 'after_closing' })
    const { services } = await votingApp()
    await table()
    await act(async () => { await creatorCommands(services).transition(pollId, 'reopen', { expires_at: null }) })
    await screen.findByRole('button', { name: 'Submit vote' })
    // Creators retain access, but any new aggregate must be server-rechecked for the new context.
    expect(services.queryClient.getQueryCache().findAll({ queryKey: ['poll-results'] }).some(query => String(query.queryKey[3]).includes('"closed"'))).toBe(false)
  })
})

describe('stale reads, revocation and expiration', () => {
  it('discards a late protected results response after the account logs out', async () => {
    const pending = deferred<Response>()
    const { state, aggregate } = votingFixture({ results_visibility: 'after_voting' }, path => path === resultsUrl ? pending.promise : undefined)
    state.ballot = submitted()
    const { services } = await votingApp()
    await screen.findByRole('radio', { name: /Morning/ })
    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    await screen.findByRole('link', { name: 'Sign in to participate' })
    await act(async () => pending.resolve(json(aggregate())))
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(services.queryClient.getQueryCache().findAll({ queryKey: ['poll-results'] })).toHaveLength(0)
  })
  it('purges results and the local capability when a private results read becomes inaccessible', async () => {
    let revoked = false
    votingFixture({ visibility: 'private' }, path => path === resultsUrl && revoked ? failure(404) : undefined)
    const { services } = await votingApp({ guest: true, captured: { token: shareToken, expectedPoll: pollId } })
    await table()
    revoked = true
    await act(async () => services.queryClient.refetchQueries({ queryKey: ['poll-results'] }))
    await screen.findByRole('heading', { name: "We couldn't open this poll." })
    expect(services.shares.has(pollId)).toBe(false)
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(services.queryClient.getQueryCache().findAll({ queryKey: ['poll-results'] })).toHaveLength(0)
  })
  it('keeps a valid private read grant on results-policy denial without caching tokens or counts', async () => {
    votingFixture({ visibility: 'private', results_visibility: 'after_voting' })
    const { services } = await votingApp({ captured: { token: shareToken, expectedPoll: pollId } })
    await screen.findByText(/Results are available only after your account has voted/)
    expect(services.shares.has(pollId)).toBe(true)
    expect(JSON.stringify(services.queryClient.getQueryCache().getAll().map(query => [query.queryKey, query.state]))).not.toContain(shareToken)
    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })
  it('preserves unsaved choices but disables submission when a saved-ballot recheck fails', async () => {
    let failed = false
    votingFixture({}, path => path === ballotUrl && failed ? failure(503) : undefined)
    const { services } = await votingApp()
    await userEvent.click(await screen.findByRole('radio', { name: /Morning/ }))
    failed = true
    await act(async () => services.queryClient.refetchQueries({ queryKey: ['ballot'] }))
    await screen.findByText(/Saved selections could not be rechecked/)
    expect(screen.getByRole('radio', { name: /Morning/ })).toBeChecked()
    expect(screen.getByRole('button', { name: 'Submit vote' })).toBeDisabled()
    failed = false
    await userEvent.click(screen.getByRole('button', { name: 'Reload saved selections' }))
    await screen.findByText('Saved selections reloaded. Review them before making changes.')
    expect(screen.getByRole('radio', { name: /Morning/ })).not.toBeChecked()
  })
})


it('updates the page clock at the closing deadline, making an open ballot ineligible', async () => {
  vi.useFakeTimers()
  try {
    const { state } = votingFixture({ expires_at: new Date(Date.now() + 60_000).toISOString() })
    const { result } = renderHook(() => useNow(state.poll.expires_at))
    expect(pollOpen(state.poll, result.current)).toBe(true)
    await act(async () => vi.advanceTimersByTimeAsync(60_001))
    expect(result.current).toBeGreaterThanOrEqual(Date.parse(state.poll.expires_at!))
    expect(pollOpen(state.poll, result.current)).toBe(false)
  } finally { vi.useRealTimers() }
})

it('rechecks a deadline that elapsed while the poll detail request was pending', async () => {
  vi.useFakeTimers()
  try {
    const deadline = new Date(Date.now() + 1000).toISOString()
    const { result, rerender } = renderHook(({ expires }: { expires: string | null }) => useNow(expires), { initialProps: { expires: null } as { expires: string | null } })
    await act(async () => vi.advanceTimersByTimeAsync(1001))
    expect(result.current).toBeLessThan(Date.parse(deadline))
    rerender({ expires: deadline })
    await act(async () => vi.advanceTimersByTimeAsync(1))
    expect(result.current).toBeGreaterThanOrEqual(Date.parse(deadline))
  } finally { vi.useRealTimers() }
})
