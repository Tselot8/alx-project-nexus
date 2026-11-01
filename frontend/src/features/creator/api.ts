import { useQuery } from '@tanstack/react-query'
import type { Services } from '../../app/services'
import type { Paginated, PollDetail, PollStatus, PollSummary } from '../../api/contracts'
import { ApiError } from '../../api/http'
import { queryKeys, uuidPattern } from '../polls/api'

export interface PollWrite {
  question: string; description: string | null; category: string | null
  visibility: 'public' | 'private'; voting_mode: 'single' | 'multiple'
  min_selections: number; max_selections: number | null
  results_visibility: PollDetail['results_visibility']; expires_at: string | null
}
export interface MineFilters { q: string; status: PollStatus | ''; category: string; sort: 'newest' | 'oldest' | 'closing_soon'; page: number }
export interface ShareStatus { poll_id: string; active: boolean; generation: number | null }
interface IssuedShare { poll_id: string; generation: number; token: string }
export const creatorKeys = {
  detail: (id: string, user: string, generation: number) => ['creator-poll', id, user, generation] as const,
  mine: (user: string, generation: number, filters: MineFilters) => [...queryKeys.myPolls(user), generation, filters] as const,
  share: (id: string, user: string, generation: number) => ['poll-share', id, user, generation] as const,
}
export function useCreatorPoll(services: Services, id: string, user: string) {
  return useQuery({
    queryKey: creatorKeys.detail(id, user, services.session.generation),
    queryFn: async ({ signal }) => {
      const poll = await services.api.request<PollDetail>('/api/v2/polls/' + id + '/', { auth: 'required', signal })
      if (poll.created_by !== user) throw new ApiError(403, 'not_owner', 'Only the creator can manage this poll.')
      return poll
    },
    enabled: uuidPattern.test(id), staleTime: 0, gcTime: 0, refetchOnWindowFocus: 'always',
  })
}
export function useMyPolls(services: Services, user: string, filters: MineFilters) {
  return useQuery({
    queryKey: creatorKeys.mine(user, services.session.generation, filters),
    queryFn: async ({ signal }) => {
      const params = new URLSearchParams({ page: String(filters.page), sort: filters.sort })
      if (filters.q) params.set('q', filters.q)
      if (filters.status) params.set('status', filters.status)
      if (filters.category) params.set('category', filters.category)
      const data = await services.api.request<Paginated<PollSummary>>('/api/v2/polls/mine/?' + params, { auth: 'required', signal })
      if (data.results.some(poll => poll.created_by !== user)) throw new ApiError(502, 'invalid_response', 'Your poll list could not be verified.')
      return data
    },
    staleTime: 0, gcTime: 0,
  })
}
export function useShareStatus(services: Services, id: string, user: string) {
  return useQuery({
    queryKey: creatorKeys.share(id, user, services.session.generation),
    queryFn: async ({ signal }) => {
      const data = await services.api.request<ShareStatus>('/api/v2/polls/' + id + '/share/', { auth: 'required', signal })
      if (data.poll_id !== id || typeof data.active !== 'boolean' || (data.generation !== null && (!Number.isSafeInteger(data.generation) || data.generation < 1))) {
        throw new ApiError(502, 'invalid_response', 'Sharing status could not be verified.')
      }
      // Only non-secret metadata may enter this query cache.
      return { poll_id: data.poll_id, active: data.active, generation: data.generation }
    },
    staleTime: 0, gcTime: 0,
  })
}
/** One identity-bound command group, no mutation cache, no automatic write retry on network errors. */
export function creatorCommands(services: Services) {
  const generation = services.session.generation
  const check = () => { if (generation !== services.session.generation) throw new DOMException('Session changed', 'AbortError') }
  async function write<T>(path: string, method: 'POST' | 'PATCH' | 'DELETE', body: unknown = {}): Promise<T> {
    check()
    // Clear permission-sensitive aggregates before lifecycle/configuration writes.
    services.queryClient.removeQueries({ queryKey: ['poll-results'] })
    try {
      const result = await services.api.request<T>(path, { method, body, auth: 'required' })
      check()
      return result
    } finally {
      if (generation === services.session.generation) {
        for (const key of ['public-polls', 'my-polls', 'poll', 'creator-poll', 'poll-share', 'ballot', 'poll-results']) {
          void services.queryClient.invalidateQueries({ queryKey: [key] })
        }
      }
    }
  }
  return {
    create: (data: PollWrite & { options: { option_text: string }[] }) => write<PollDetail>('/api/v2/polls/', 'POST', data),
    update: (id: string, data: Partial<PollWrite>) => write<PollDetail>('/api/v2/polls/' + id + '/', 'PATCH', data),
    remove: (id: string) => write<void>('/api/v2/polls/' + id + '/', 'DELETE'),
    transition: (id: string, action: 'publish' | 'close' | 'reopen' | 'archive', data: { expires_at: string | null } | Record<string, never> = {}) =>
      write<PollDetail>('/api/v2/polls/' + id + '/' + action + '/', 'POST', data),
    option: (id: string, text: string, optionId?: string) => write<{ id: string; option_text: string }>(
      '/api/v2/polls/' + id + '/options/' + (optionId ? optionId + '/' : ''), optionId ? 'PATCH' : 'POST', { option_text: text }),
    removeOption: (id: string, optionId: string) => write<void>('/api/v2/polls/' + id + '/options/' + optionId + '/', 'DELETE'),
    share: async (id: string, action: 'issue' | 'regenerate' | 'revoke') => {
      const result = await write<IssuedShare | undefined>('/api/v2/polls/' + id + '/share/' + (action === 'regenerate' ? 'regenerate/' : ''),
        action === 'revoke' ? 'DELETE' : 'POST')
      check()
      services.shares.revoke(id)
      const current = services.session.getSnapshot()
      if (action === 'revoke') {
        if (current.status === 'authenticated') services.queryClient.setQueryData(creatorKeys.share(id, current.user.id, generation), { poll_id: id, active: false, generation: null })
        return null
      }
      if (!result || result.poll_id !== id || !Number.isSafeInteger(result.generation) || result.generation < 1 || !/^[A-Za-z0-9_-]{43}$/.test(result.token)) {
        throw new ApiError(502, 'invalid_response', 'The new link could not be verified. Reload sharing status before trying again.')
      }
      if (current.status === 'authenticated') services.queryClient.setQueryData(creatorKeys.share(id, current.user.id, generation), {
        poll_id: id, active: true, generation: result.generation,
      })
      return { url: window.location.origin + '/polls/' + id + '#share=' + result.token, generation: result.generation }
    },
  }
}
