import { useEffect, useRef, useState } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router'
import { useServices, useSession } from './providers'
import { Button, Feedback, Initials } from '../ui/components'

const links = [{ to: '/', label: 'Home' }, { to: '/polls', label: 'Explore polls' }, { to: '/my-polls', label: 'My polls' }]
function Brand() {
  return <Link to="/" className="brand" aria-label="Project Nexus home">
    <span className="brand-mark" aria-hidden="true"><i /><i /><i /></span>Nexus<span className="brand-dot">.</span>
  </Link>
}
export function Layout({ notice }: { notice?: React.ReactNode }) {
  const snapshot = useSession()
  const { session } = useServices()
  const [open, setOpen] = useState(false)
  const [loggingOut, setLoggingOut] = useState(false)
  const [logoutError, setLogoutError] = useState(false)
  const menu = useRef<HTMLButtonElement>(null)
  const location = useLocation()
  const main = useRef<HTMLElement>(null)
  useEffect(() => { main.current?.focus({ preventScroll: true }) }, [location.pathname])
  const close = () => setOpen(false)
  const signOut = async () => {
    setLoggingOut(true); setLogoutError(false); close()
    try { await session.logout() } catch { setLogoutError(true) }
    finally { setLoggingOut(false) }
  }
  const accountLinks = <>
    {snapshot.status === 'authenticated' ? <>
      <Link to="/profile" aria-label="My profile" className="account-link" onClick={close}><Initials name={snapshot.user.username} /><span>My profile</span></Link>
      <Button variant="quiet" pending={loggingOut} onClick={() => { void signOut() }}>Sign out</Button>
    </> : snapshot.status === 'restoring' ? <span className="nav-status">Checking session…</span> : <>
      <Link className="button button--quiet" to="/login" onClick={close}>Sign in</Link>
      <Link className="button button--secondary" to="/register" onClick={close}>Join Nexus</Link>
    </>}
  </>
  return <div className="app-shell">
    <a className="skip-link" href="#main-content">Skip to content</a>
    <header className="site-header" onKeyDown={event => {
      if (event.key === 'Escape' && open) { close(); menu.current?.focus() }
    }}>
      <div className="header-inner container"><Brand />
        <nav className="desktop-nav" aria-label="Main">{links.map(link =>
          <NavLink key={link.to} to={link.to} end={link.to === '/'}>{link.label}</NavLink>)}</nav>
        <div className="desktop-actions">{accountLinks}<Link to="/polls/new" className="button button--primary">Create poll <span aria-hidden="true">+</span></Link></div>
        <button className="button button--secondary mobile-menu-toggle" ref={menu} aria-expanded={open}
          aria-controls="mobile-navigation" onClick={() => setOpen(!open)}>{open ? 'Close menu' : 'Menu'}</button>
      </div>
      <nav id="mobile-navigation" className="mobile-nav container" hidden={!open} aria-label="Mobile">
        {links.map(link => <NavLink key={link.to} to={link.to} end={link.to === '/'} onClick={close}>{link.label}</NavLink>)}
        <Link to="/polls/new" onClick={close}>Create poll</Link>{accountLinks}
      </nav>
    </header>
    <main id="main-content" className="container main-content" tabIndex={-1} ref={main}>
      {notice}
      {logoutError && <Feedback tone="error">You are signed out on this page, but server sign-out could not be confirmed. Recheck your connection before reloading.
        <Button variant="secondary" pending={loggingOut} onClick={() => { void signOut() }}>Retry sign out</Button>
      </Feedback>}
      <Outlet />
    </main>
    <footer className="site-footer"><div className="container footer-inner"><Brand />
      <p>Your perspective. A clearer picture.</p><span>© {new Date().getFullYear()} Project Nexus</span>
    </div></footer>
  </div>
}
