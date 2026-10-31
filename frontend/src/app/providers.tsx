import { createContext, useContext, useEffect, useSyncExternalStore } from 'react'
import type { ReactNode } from 'react'
import { QueryClientProvider } from '@tanstack/react-query'
import { Navigate, Outlet, useLocation } from 'react-router'
import type { Services } from './services'
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
  return <Outlet key={session.user.id + ':' + actions.generation} />
}
