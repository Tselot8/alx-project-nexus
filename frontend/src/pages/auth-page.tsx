import { useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, Navigate, useLocation, useSearchParams } from 'react-router'
import { useServices, useSession } from '../app/providers'
import { ApiError } from '../api/http'
import { safeReturnTo } from '../auth/navigation'
import { Button, Card, Feedback, Field } from '../ui/components'
import { BallotArtwork } from '../ui/illustrations'

export function AuthPage({ register = false }: { register?: boolean }) {
  const { session } = useServices()
  const snapshot = useSession()
  const [params] = useSearchParams()
  const location = useLocation()
  const destination = safeReturnTo(params.get('returnTo'))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const errorSummary = useRef<HTMLDivElement>(null)
  if (snapshot.status === 'authenticated') return <Navigate replace to={destination} />
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (busy) return
    const form = event.currentTarget
    const data = new FormData(form)
    setBusy(true); setError(null)
    const email = String(data.get('email') || '')
    const password = String(data.get('password') || '')
    try {
      if (register) await session.register({ username: String(data.get('username') || ''), email, password })
      else await session.login({ email, password })
      form.reset()
    } catch (failure) {
      if (!(failure instanceof DOMException && failure.name === 'AbortError')) {
        setError(failure instanceof ApiError ? failure : new ApiError(0, 'request_failed', 'Please try again.'))
        requestAnimationFrame(() => errorSummary.current?.focus())
      }
    } finally { setBusy(false) }
  }
  const alternate = (register ? '/login' : '/register') + '?returnTo=' + encodeURIComponent(destination)
  return <section className="auth-layout"><div className="auth-intro"><div className="auth-copy">
    <p className="eyebrow">Your place in the conversation</p>
    <h1>{register ? 'Every voice starts somewhere.' : 'Welcome back to Nexus.'}</h1>
    <p className="page-lead">{register ? 'A question you want to ask. An opinion you want to share. Make a little room for both.' : 'Good to see you again. Your questions and conversations are right where you left them.'}</p>
    </div><div className="auth-art"><BallotArtwork compact /></div>
  </div><Card className="auth-card"><h2>{register ? 'Create your account' : 'Sign in'}</h2>
    <p>{register ? 'Start with the essentials.' : 'Use the email address for your account.'}</p>
    {typeof location.state?.accountNotice === 'string' && <Feedback>{location.state.accountNotice}</Feedback>}
    {error && <div ref={errorSummary} tabIndex={-1}><Feedback tone="error">{error.message}</Feedback></div>}
    <form method="post" onSubmit={event => { void submit(event) }} aria-label={register ? 'Registration' : 'Sign in'} aria-busy={busy}>
      {register && <Field label="Username" name="username" autoComplete="username" maxLength={50} required disabled={busy} error={error?.fieldErrors.username} />}
      <Field label="Email address" name="email" type="email" autoComplete={register ? 'email' : 'username'} maxLength={100} required disabled={busy} error={error?.fieldErrors.email} />
      <Field label="Password" name="password" type="password" autoComplete={register ? 'new-password' : 'current-password'}
        minLength={register ? 8 : undefined} maxLength={1024} required disabled={busy}
        hint={register ? 'Use a strong, unique password with at least 8 characters.' : undefined}
        error={error?.fieldErrors.password} />
      {error?.fieldErrors.account && <Feedback tone="error">{error.fieldErrors.account.join(' ')}</Feedback>}
      <Button type="submit" pending={busy}>{busy ? 'Please wait…' : register ? 'Create account' : 'Sign in'}<span aria-hidden="true">↗</span></Button>
    </form>
    <p className="auth-switch">{register ? 'Already have an account?' : 'New to Nexus?'} <Link to={alternate}>{register ? 'Sign in' : 'Create an account'}</Link></p>
    <p className="supporting-copy"><Link to="/forgot-password">Forgot your password?</Link> Secure email recovery is not available yet.</p>
  </Card></section>
}
