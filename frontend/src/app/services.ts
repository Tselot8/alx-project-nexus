import { QueryClient } from '@tanstack/react-query'
import { ApiClient } from '../api/client'
import { ApiError, HttpClient } from '../api/http'
import { Session } from '../auth/session'
import { ShareVault } from '../features/sharing/share-vault'

export function createServices() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        retry: (attempt, error) => attempt < 1 && (!(error instanceof ApiError) || error.status === 0 || error.status >= 500),
      },
      mutations: { retry: false },
    },
  })
  const http = new HttpClient()
  const shares = new ShareVault(http)
  const session = new Session(http, () => {
    // clear() destroys active queries and cancels their signals before removal.
    queryClient.clear()
  })
  return { queryClient, session, shares, api: new ApiClient(http, session, shares) }
}
export type Services = ReturnType<typeof createServices>
