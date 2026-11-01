import { useLayoutEffect, useState } from 'react'
import { Link, Outlet, useLocation, useNavigate } from 'react-router'
import { useServices } from '../../app/providers'
import { capturePrivateShare } from './share-vault'
import type { CapturedShare } from './share-vault'
import { Card, Loading } from '../../ui/components'

export function UnavailablePoll() {
  return <section className="page-section"><Card>
    <p className="eyebrow">Poll unavailable</p><h1>We couldn't open this poll.</h1>
    <p>The link may be invalid, revoked, or no longer accessible. If this was a private poll, reopen the original shared link or ask its creator for a current one.</p>
    <p>Private links stay in this tab only. Reloading a page after the link has been removed from the address bar requires reopening the original link.</p>
    <Link className="button button--secondary" to="/polls">Explore public polls</Link>
  </Card></section>
}

/** Suspends the routed content until a fragment is resolved; credentials never enter query state. */
export function ShareGate({ captured }: { captured: CapturedShare }) {
  const location = useLocation()
  const navigate = useNavigate()
  const { shares } = useServices()
  const [consumed, setConsumed] = useState(false)
  const [initialPath] = useState(location.pathname)
  const incoming = location.hash.startsWith('#share=')
  const initial = !consumed && captured !== null && location.pathname === initialPath
  useLayoutEffect(() => {
    if (!incoming && !initial) return
    const controller = new AbortController()
    // Replacing a capability invalidates all old scoped detail queries first.
    shares.clear()
    const value = incoming ? capturePrivateShare({
      location: { hash: location.hash, pathname: location.pathname, search: location.search } as Location,
      history: window.history,
    }) : captured
    if (!value) return
    void shares.resolve(value, controller.signal).then(id => {
      setConsumed(true)
      navigate('/polls/' + id, { replace: true })
    }, () => {
      if (controller.signal.aborted) return
      setConsumed(true)
      navigate(location.pathname + location.search, { replace: true, state: { nexusShareUnavailable: true } })
    })
    return () => controller.abort()
  }, [incoming, initial, captured, location.hash, location.pathname, location.search, navigate, shares])
  if (incoming || initial) return <Loading label="Checking your private link…" />
  if (location.state?.nexusShareUnavailable === true) return <UnavailablePoll />
  return <Outlet />
}
