import { useQuery } from '@tanstack/react-query'
import type { ApiClient } from '../../api/client'
import type { Category, Paginated, PollDetail, PollSummary } from '../../api/contracts'

export interface DiscoveryFilters {
  q?: string; category?: string; page?: number
  sort?: 'newest' | 'oldest' | 'closing_soon'
  status?: 'published' | 'closed'
}
export const queryKeys = {
  publicPolls: (filters: DiscoveryFilters = {}) => ['public-polls', filters] as const,
  poll: (id: string, scope: string) => ['poll', id, scope] as const,
  myPolls: (userId: string) => ['my-polls', userId] as const,
  categories: ['categories'] as const,
  categoryPage: (page: number) => ['categories', page] as const,
}
export const uuidPattern = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i
export function discoveryPath(filters: DiscoveryFilters): string {
  const search = new URLSearchParams()
  if (filters.q) search.set('q', filters.q)
  if (filters.category) search.set('category', filters.category)
  if (filters.page) search.set('page', String(filters.page))
  if (filters.sort) search.set('sort', filters.sort)
  if (filters.status) search.set('status', filters.status)
  return '/api/v2/polls/' + (search.size ? '?' + search.toString() : '')
}
export function usePublicPolls(api: ApiClient, filters: DiscoveryFilters = {}) {
  return useQuery({
    queryKey: queryKeys.publicPolls(filters),
    queryFn: ({ signal }) => api.request<Paginated<PollSummary>>(discoveryPath(filters), { signal }),
  })
}
export function useCategories(api: ApiClient, page: number) {
  return useQuery({
    queryKey: queryKeys.categoryPage(page),
    queryFn: ({ signal }) => api.request<Paginated<Category>>('/api/v2/categories/?page=' + page, { signal }),
    staleTime: 300_000,
  })
}
export function usePoll(api: ApiClient, id: string, scope: string, authenticated: boolean, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.poll(id, scope),
    queryFn: ({ signal }) => api.request<PollDetail>('/api/v2/polls/' + id + '/', {
      signal, auth: authenticated ? 'required' : 'none',
    }),
    enabled: enabled && uuidPattern.test(id),
    // Details can include private/draft content or owner-only metadata.
    // Revalidate on every visit/focus; never retain unobserved detail data.
    staleTime: 0,
    gcTime: 0,
    refetchOnMount: 'always',
    refetchOnWindowFocus: 'always',
  })
}
