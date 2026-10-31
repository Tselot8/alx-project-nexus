import { createContext, useContext, useEffect, useState, useSyncExternalStore } from 'react'
import type { ReactNode } from 'react'
import { QueryClientProvider } from '@tanstack/react-query'
import { Navigate, Outlet, useLocation } from 'react-router'
import type { Services } from './services'
import type { CapturedShare } from '../features/sharing/share-vault'
import { safeReturnTo } from '../auth/navigation'
import { Button, Card, Feedback, Loading } from '../ui/components'

const ServicesContext = createContext<Services | null>(null)
export function useServices(): Services {
  const value = useContext(ServicesContext)
  if (!value) throw new Error('Application providers are missing.')
  return value
}
export function useSession() {
  const { session } = useServices()
  return useSyncExternalStore(session.subscribe, session.getSnapshot, session.getSnapshot)
}
export function Providers({ services, children }: { services: Services; children: ReactNode }) {
  useEffect(() => { void services.session.restore() }, [services])
  return <ServicesContext.Provider value={services}>
    <QueryClientProvider client={services.queryClient}>{children}</QueryClientProvider>
  </ServicesContext.Provider>
}
export function ProtectedRoute() {
  const session = useSession()
  const { session: actions } = useServices()
  const location = useLocation()
  if (session.status === 'restoring') return <Loading label="Checking your session…" />
  if (session.status === 'unavailable') return <Card><Feedback tone="error">{session.message}</Feedback>
    <Button onClick={() => { void actions.restore(true) }}>Retry session check</Button></Card>
  if (session.status === 'anonymous') {
    return <Navigate replace to={'/login?returnTo=' + encodeURIComponent(safeReturnTo(location.pathname))} />
  }
  return <Outlet />
}
export function PrivateShareNotice({ captured }: { captured: CapturedShare }) {
  const { shares } = useServices()
  const [status, setStatus] = useState<'idle' | 'loading' | 'resolved' | 'failed'>(captured ? 'loading' : 'idle')
  // Resolution is a safe, repeatable read operation. StrictMode cleanup cancels
  // its first request; no token is ever copied into React state or query data.
  useEffect(() => {
    if (!captured) return
    const controller = new AbortController()
    void shares.resolve(captured, controller.signal).then(() => {
      setStatus('resolved')
    }, () => {
      if (!controller.signal.aborted) setStatus('failed')
    })
    return () => controller.abort()
  }, [captured, shares])
  if (status === 'loading') return <Loading label="Checking your private link…" />
  if (status === 'resolved') return <Feedback tone="success">Private link verified for this tab. The full poll experience is coming soon. Reopen the original link after a page refresh.</Feedback>
  if (status === 'failed') return <Feedback tone="error">This private link is unavailable. Ask the creator for a current link.</Feedback>
  return null
}
