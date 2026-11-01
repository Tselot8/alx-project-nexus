import { describe, expect, it, vi } from 'vitest'
import { createServices } from '../../app/services'
import { queryKeys } from '../polls/api'
import { alice, bob, deferred, failure, json, otherPollId, pollId } from '../../test/network'
import { ballotStamp, percentage, pollOpen, readBallot, readResults, resultsPotential, selectionErrors, submitBallot } from './api'
import { afternoon, morning, submitted, unsent, votingFixture } from './test-fixture'

describe('ballot and aggregate contracts', () => {
  it('sanitizes ballot data without inventing a legacy update timestamp', () => {
    expect(readBallot({ ...submitted([morning], null), user_email: 'private@example.invalid' }, pollId)).toEqual(submitted([morning], null))
    expect(readBallot(unsent(), pollId)).toEqual(unsent())
  })
  it.each([
    { ...unsent(), poll_id: otherPollId }, { ...unsent(), option_ids: [morning] },
    { ...submitted(), option_ids: [morning, morning] }, { ...submitted(), submitted_at: null },
    { ...submitted(), option_ids: ['invalid-option'] },
  ])('rejects inconsistent ballot data %j', value => { expect(() => readBallot(value, pollId)).toThrow() })
  it('validates empty, duplicate, foreign and multi-choice cardinality', () => {
    const { state } = votingFixture()
    expect(selectionErrors(state.poll, [])).not.toEqual([])
    expect(selectionErrors(state.poll, [morning, morning])).not.toEqual([])
    expect(selectionErrors(state.poll, [otherPollId])).not.toEqual([])
    expect(selectionErrors(state.poll, [morning, afternoon])).not.toEqual([])
    state.poll.voting_mode = 'multiple'; state.poll.min_selections = 2; state.poll.max_selections = 2
    expect(selectionErrors(state.poll, [morning])).not.toEqual([])
    expect(selectionErrors(state.poll, [morning, afternoon])).toEqual([])
  })
  it('uses the correct percentage denominators for multiple selections', () => {
    const { state, aggregate } = votingFixture({ voting_mode: 'multiple' })
    state.others = [[morning, afternoon], [morning]]
    const result = readResults({ ...aggregate(), voters: [{ email: 'never-expose@example.invalid' }] }, state.poll)
    expect(result.total_participants).toBe(2)
    expect(result.total_selections).toBe(3)
    expect(result.options[0]).toMatchObject({ count: 2, percentage_of_participants: 100, percentage_of_selections: 66.67 })
    expect(result).not.toHaveProperty('voters')
    expect(percentage(1, 3)).toBe(33.33)
    expect(percentage(1, 0)).toBe(0)
  })
  it.each(['wrong_poll', 'unknown_option', 'duplicate_option', 'negative_count', 'infinite_percent', 'wrong_denominator', 'wrong_total'])('rejects unverified aggregate %s', defect => {
    const { state, aggregate } = votingFixture()
    state.others = [[morning]]
    const result = aggregate()
    if (defect === 'wrong_poll') result.poll_id = otherPollId
    if (defect === 'unknown_option') result.options[0]!.id = otherPollId
    if (defect === 'duplicate_option') result.options[1]!.id = result.options[0]!.id
    if (defect === 'negative_count') result.options[0]!.count = -1
    if (defect === 'infinite_percent') result.options[0]!.percentage_of_participants = Infinity
    if (defect === 'wrong_denominator') result.options[0]!.percentage_of_selections = 50
    if (defect === 'wrong_total') result.total_selections = 44
    expect(() => readResults(result, state.poll)).toThrow()
  })
  it('keeps user cache keys separate and participation timestamps in the ballot stamp', () => {
    expect(queryKeys.ballot(pollId, alice.id, 1)).not.toEqual(queryKeys.ballot(pollId, bob.id, 1))
    expect(queryKeys.ballot(pollId, alice.id, 1)).not.toEqual(queryKeys.ballot(pollId, alice.id, 2))
    expect(ballotStamp(submitted())).not.toBe(ballotStamp(submitted([afternoon])))
  })
  it('applies the exact closing boundary and does not grant guest after-voting access', () => {
    const { state } = votingFixture({ expires_at: '2035-01-01T00:00:00Z', results_visibility: 'after_voting' })
    expect(pollOpen(state.poll, Date.parse(state.poll.expires_at!))).toBe(false)
    expect(resultsPotential(state.poll, null, Date.now())).toBe(false)
    expect(resultsPotential(state.poll, state.poll.created_by, Date.now())).toBe(true)
  })
  it('never writes through share access or uses legacy vote routes', async () => {
    const { state, fetcher } = votingFixture({ visibility: 'private', created_by: bob.id })
    const services = createServices()
    await services.session.login({ email: alice.email, password: 'fixture' })
    await expect(submitBallot(services, state.poll, [morning])).rejects.toMatchObject({ status: 403 })
    expect(fetcher.mock.calls.some(([path]) => String(path).includes('/ballots/'))).toBe(false)
    expect(fetcher.mock.calls.every(([path]) => String(path).startsWith('/api/v2/'))).toBe(true)
  })
  it('rejects an unverified server receipt without claiming a saved vote', async () => {
    const { state } = votingFixture({}, path => path.endsWith('/ballots/') ? json(submitted([afternoon])) : undefined)
    const services = createServices()
    await services.session.login({ email: alice.email, password: 'fixture' })
    await expect(submitBallot(services, state.poll, [morning])).rejects.toMatchObject({ status: 502 })
  })
  it('maps a paused voting backend without changing settings or falling back', async () => {
    const { state, fetcher } = votingFixture({}, path => path.endsWith('/ballots/') ? failure(503, { detail: 'Paused' }, 'voting_paused') : undefined)
    const services = createServices()
    await services.session.login({ email: alice.email, password: 'fixture' })
    await expect(submitBallot(services, state.poll, [morning])).rejects.toMatchObject({ code: 'voting_paused' })
    expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST' && String(init.body).includes('option_ids'))).toHaveLength(1)
  })
})

describe('submission session fences', () => {
  it('does not submit as a new account if cancellation yields during an account switch', async () => {
    const { state, fetcher } = votingFixture()
    const services = createServices()
    await services.session.login({ email: alice.email, password: 'fixture' })
    const pending = deferred<void>()
    const cancel = vi.spyOn(services.queryClient, 'cancelQueries').mockReturnValueOnce(pending.promise)
    const attempt = submitBallot(services, state.poll, [morning]).catch(error => error)
    await services.session.login({ email: bob.email, password: 'fixture' })
    pending.resolve()
    expect(await attempt).toMatchObject({ name: 'AbortError' })
    expect(state.writes).toBe(0)
    expect(fetcher.mock.calls.some(([path]) => String(path).endsWith('/ballots/'))).toBe(false)
    cancel.mockRestore()
  })
  it('discards a late ballot receipt after logout without restoring old account data', async () => {
    const pending = deferred<Response>()
    const { state, fetcher } = votingFixture({}, (path, init) => path.endsWith('/ballots/') && init.method === 'POST' ? pending.promise : undefined)
    const services = createServices()
    await services.session.login({ email: alice.email, password: 'fixture' })
    const attempt = submitBallot(services, state.poll, [morning]).catch(error => error)
    await vi.waitFor(() => expect(fetcher.mock.calls.some(([path]) => String(path).endsWith('/ballots/'))).toBe(true))
    await services.session.logout()
    pending.resolve(json(submitted()))
    expect(await attempt).toMatchObject({ name: 'AbortError' })
    expect(services.queryClient.getQueryCache().findAll({ queryKey: ['ballot'] })).toHaveLength(0)
    expect(services.session.getSnapshot().status).toBe('anonymous')
  })
})


it('does not recreate an unobserved ballot cache after a confirmed submission', async () => {
  const { state } = votingFixture()
  const services = createServices()
  await services.session.login({ email: alice.email, password: 'fixture' })
  const receipt = await submitBallot(services, state.poll, [morning])
  expect(receipt.submitted).toBe(true)
  expect(state.ballot.option_ids).toEqual([morning])
  expect(services.queryClient.getQueryCache().findAll({ queryKey: ['ballot'] })).toHaveLength(0)
})
