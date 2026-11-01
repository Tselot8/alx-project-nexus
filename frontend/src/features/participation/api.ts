import { useQuery } from '@tanstack/react-query'
import type { Ballot, PollDetail, PollResults } from '../../api/contracts'
import { ApiError, isRecord } from '../../api/http'
import type { Services } from '../../app/services'
import { queryKeys, uuidPattern } from '../polls/api'

const invalid = () => new ApiError(502, 'invalid_response', 'The service response could not be verified. Reload before continuing.')
const timestamp = (value: unknown) => value === null || (typeof value === 'string' && Number.isFinite(Date.parse(value)))
export function readBallot(value: unknown, pollId: string): Ballot {
  if (!isRecord(value) || value.poll_id !== pollId || typeof value.submitted !== 'boolean'
    || !Array.isArray(value.option_ids) || value.option_ids.length > 100
    || !value.option_ids.every((id): id is string => typeof id === 'string' && uuidPattern.test(id))
    || new Set(value.option_ids).size !== value.option_ids.length
    || !timestamp(value.submitted_at) || !timestamp(value.updated_at)
    || (value.submitted ? value.submitted_at === null || value.option_ids.length === 0 : value.submitted_at !== null || value.option_ids.length !== 0)) throw invalid()
  return { poll_id: pollId, option_ids: [...value.option_ids], submitted: value.submitted,
    submitted_at: value.submitted_at as string | null, updated_at: value.updated_at as string | null }
}
export const sameChoices = (a: readonly string[], b: readonly string[]) => a.length === b.length && a.every(id => b.includes(id))
export function ballotStamp(ballot: Ballot) {
  return JSON.stringify([ballot.submitted, ballot.submitted_at, ballot.updated_at, [...ballot.option_ids].sort()])
}
export function pollOpen(poll: PollDetail, now = Date.now()) {
  return poll.status === 'published' && (!poll.expires_at || Date.parse(poll.expires_at) > now)
}
export function selectionErrors(poll: PollDetail, ids: readonly string[]): string[] {
  if (!ids.length) return ['Choose at least one option. A submitted ballot cannot be withdrawn.']
  if (new Set(ids).size !== ids.length || ids.some(id => !poll.options.some(option => option.id === id))) return ['The options changed. Reload the poll and your saved selections before submitting.']
  if (poll.voting_mode === 'single' && ids.length !== 1) return ['Choose exactly one option.']
  if (poll.voting_mode === 'multiple' && (ids.length < poll.min_selections || (poll.max_selections !== null && ids.length > poll.max_selections))) {
    return ['Choose ' + (poll.max_selections === null ? 'at least ' + poll.min_selections : poll.min_selections + '–' + poll.max_selections) + ' options.']
  }
  return []
}
export function resultsPotential(poll: PollDetail, userId: string | null, now: number) {
  if (userId === poll.created_by) return true
  if (poll.results_visibility === 'immediate') return true
  if (poll.results_visibility === 'after_voting') return userId !== null
  return poll.status === 'closed' || poll.status === 'archived' || (poll.status === 'published' && !!poll.expires_at && Date.parse(poll.expires_at) <= now)
}
export function resultContext(poll: PollDetail) {
  return JSON.stringify([poll.status, poll.visibility, poll.results_visibility, poll.expires_at, poll.voting_mode,
    poll.min_selections, poll.max_selections, poll.version ?? null, poll.options.map(option => option.id).sort()])
}
const count = (value: unknown): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
export const percentage = (votes: number, denominator: number) => denominator ? Math.round(10_000 * votes / denominator) / 100 : 0
/** Only verified aggregate fields enter the query cache; unexpected identities are discarded. */
export function readResults(value: unknown, poll: PollDetail): PollResults {
  if (!isRecord(value) || value.poll_id !== poll.id || typeof value.question !== 'string'
    || typeof value.authority !== 'string' || !['bridge', 'ballots'].includes(value.authority) || !count(value.total_participants) || !count(value.total_selections)
    || !Array.isArray(value.options) || value.options.length !== poll.options.length) throw invalid()
  const participants = value.total_participants
  const selections = value.total_selections
  const seen = new Set<string>()
  const options = value.options.map((row: unknown) => {
    if (!isRecord(row) || typeof row.id !== 'string' || seen.has(row.id) || !count(row.count)
      || !poll.options.some(option => option.id === row.id && option.option_text === row.option_text)
      || row.count > participants || row.count > selections) throw invalid()
    for (const [name, denominator] of [['percentage_of_participants', participants], ['percentage_of_selections', selections]] as const) {
      const percent = row[name]
      if (typeof percent !== 'number' || !Number.isFinite(percent) || percent < 0 || percent > 100
        || Math.abs(percent - percentage(row.count, denominator)) > .011) throw invalid()
    }
    seen.add(row.id)
    return { id: row.id, option_text: row.option_text as string, count: row.count,
      percentage_of_participants: row.percentage_of_participants as number, percentage_of_selections: row.percentage_of_selections as number }
  })
  if (options.reduce((total, row) => total + row.count, 0) !== selections || selections < participants
    || (poll.voting_mode === 'single' && selections !== participants)) throw invalid()
  return { poll_id: poll.id, question: value.question, authority: value.authority as PollResults['authority'],
    total_participants: participants, total_selections: selections, options }
}
export type BallotRead = { kind: 'ok'; ballot: Ballot } | { kind: 'denied'; status: number }
export type ResultsRead = { kind: 'ok'; results: PollResults } | { kind: 'restricted' } | { kind: 'unavailable' }
  | { kind: 'error'; code: 'history' | 'service' | 'session' }
export function useBallot(services: Services, poll: PollDetail, userId: string) {
  return useQuery({
    queryKey: queryKeys.ballot(poll.id, userId, services.session.generation),
    queryFn: async ({ signal }): Promise<BallotRead> => {
      try {
        return { kind: 'ok', ballot: readBallot(await services.api.request('/api/v2/polls/' + poll.id + '/ballots/', { auth: 'required', signal }), poll.id) }
      } catch (error) {
        if (error instanceof DOMException && error.name === 'AbortError') throw error
        if (error instanceof ApiError && [401, 403, 404].includes(error.status)) return { kind: 'denied', status: error.status }
        throw new ApiError(error instanceof ApiError ? error.status : 0, 'ballot_unavailable', 'Your saved selections could not be checked. Retry before voting.')
      }
    },
    gcTime: 0, staleTime: 0, refetchOnMount: 'always', refetchOnWindowFocus: 'always', retry: false,
  })
}
export function useResults(services: Services, poll: PollDetail, scope: string, authenticated: boolean) {
  return useQuery({
    queryKey: queryKeys.results(poll.id, scope, resultContext(poll)),
    queryFn: async ({ signal }): Promise<ResultsRead> => {
      try {
        return { kind: 'ok', results: readResults(await services.api.request('/api/v2/polls/' + poll.id + '/results/', {
          auth: authenticated ? 'required' : 'none', signal,
        }), poll) }
      } catch (error) {
        if (error instanceof DOMException && error.name === 'AbortError') throw error
        // Never retain denied response bodies or a previous aggregate on read failure.
        if (error instanceof ApiError && error.status === 403) return { kind: 'restricted' }
        if (error instanceof ApiError && error.status === 404) return { kind: 'unavailable' }
        return { kind: 'error', code: error instanceof ApiError && error.status === 401 ? 'session'
          : error instanceof ApiError && error.code === 'voting_history_unavailable' ? 'history' : 'service' }
      }
    },
    gcTime: 0, staleTime: 0, refetchOnMount: 'always', refetchOnWindowFocus: 'always', retry: false,
  })
}
export async function submitBallot(services: Services, poll: PollDetail, ids: string[]): Promise<Ballot> {
  const epoch = services.session.generation
  const user = services.session.getSnapshot()
  if (user.status !== 'authenticated') throw new ApiError(401, 'session_required', 'Sign in before submitting a ballot.')
  if (poll.visibility === 'private' && user.user.id !== poll.created_by) throw new ApiError(403, 'read_only', 'This private link does not grant voting permission.')
  if (!pollOpen(poll)) throw new ApiError(400, 'poll_closed', 'Voting is closed. Your selections were not submitted.')
  const errors = selectionErrors(poll, ids)
  if (errors.length) throw new ApiError(400, 'invalid_selection', errors[0]!)
  const key = queryKeys.ballot(poll.id, user.user.id, epoch)
  await services.queryClient.cancelQueries({ queryKey: key, exact: true })
  // Cancellation yields: never adopt a newer account for this older submission.
  if (services.session.generation !== epoch) throw new DOMException('Session changed', 'AbortError')
  try {
    const saved = readBallot(await services.api.request('/api/v2/polls/' + poll.id + '/ballots/', {
      auth: 'required', method: 'POST', body: { option_ids: ids },
    }), poll.id)
    if (services.session.generation !== epoch) throw new DOMException('Session changed', 'AbortError')
    if (!saved.submitted || !sameChoices(saved.option_ids, ids)) throw invalid()
    // Navigation may have removed this zero-retention query during the write.
    if (services.queryClient.getQueryState(key)) {
      services.queryClient.setQueryData<BallotRead>(key, (): BallotRead => ({ kind: 'ok', ballot: saved }))
    }
    return saved
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    const status = error instanceof ApiError ? error.status : 0
    const paused = error instanceof ApiError && error.code === 'voting_paused'
    throw new ApiError(status, paused ? 'voting_paused' : 'submission_failed', paused ? 'Voting is temporarily paused. Try again later.'
      : status === 401 ? 'Your session ended. Sign in again before voting.'
      : status === 403 || status === 404 ? 'You no longer have access to submit a ballot for this poll.'
      : status === 409 ? 'The poll or your saved ballot changed. Reload before submitting again.'
      : status === 400 ? 'The selection set was not accepted. Review the latest poll and selection limits.'
      : 'Submission could not be confirmed. Reload your saved selections before trying again.')
  } finally {
    if (services.session.generation === epoch) {
      for (const prefix of ['ballot', 'poll-results', 'poll', 'creator-poll', 'my-polls', 'public-polls']) {
        void services.queryClient.invalidateQueries({ queryKey: [prefix] })
      }
    }
  }
}
