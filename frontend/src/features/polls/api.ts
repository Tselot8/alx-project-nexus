import { useQuery } from '@tanstack/react-query'
import type { ApiClient } from '../../api/client'
import type { Paginated, PollSummary } from '../../api/contracts'

export interface DiscoveryFilters { q?: string; category?: string; page?: number; sort?: 'newest' | 'oldest' | 'closing_soon' }
export const queryKeys = {
  publicPolls: (filters: DiscoveryFilters = {}) => ['public-polls', filters] as const,
  poll: (id: string, scope: string) => ['poll', id, scope] as const,
  myPolls: (userId: string) => ['my-polls', userId] as const,
  categories: ['categories'] as const,
}
export function discoveryPath(filters: DiscoveryFilters): string {
  const search = new URLSearchParams()
  if (filters.q) search.set('q', filters.q)
  if (filters.category) search.set('category', filters.category)
  if (filters.page) search.set('page', String(filters.page))
  if (filters.sort) search.set('sort', filters.sort)
  return '/api/v2/polls/' + (search.size ? '?' + search.toString() : '')
}
/** Foundation hook only; the complete discovery UI is reserved for H. */
export function usePublicPolls(api: ApiClient, filters: DiscoveryFilters = {}) {
  return useQuery({
    queryKey: queryKeys.publicPolls(filters),
    queryFn: ({ signal }) => api.request<Paginated<PollSummary>>(discoveryPath(filters), { signal }),
  })
}
