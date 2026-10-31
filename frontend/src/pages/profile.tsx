import { useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import type { Account } from '../api/contracts'
import { useServices, useSession } from '../app/providers'
import { ActionFeedback, TextareaField, useAction, useUnsavedChanges } from '../ui/workflow'
import { Button, Card, Feedback, Field, Initials } from '../ui/components'

export function Profile() {
  const services = useServices()
  const snapshot = useSession()
  if (snapshot.status !== 'authenticated') return null
  return <AccountSettings key={snapshot.user.id + ':' + services.session.generation} user={snapshot.user} />
}
function AccountSettings({ user }: { user: Account }) {
  const services = useServices()
  const action = useAction()
  const [values, setValues] = useState({ username: user.username, bio: user.profile.bio || '', location: user.profile.location || '' })
  const [saved, setSaved] = useState(values)
  const dirty = JSON.stringify(values) !== JSON.stringify(saved)
  useUnsavedChanges(dirty)
  async function save(event: React.FormEvent) {
    event.preventDefault()
    await action.run(async () => {
      const epoch = services.session.generation
      const data = await services.api.request<{ user: Account }>('/api/v2/auth/me/', {
        auth: 'required', method: 'PATCH',
        body: { username: values.username.trim(), profile: { bio: values.bio, location: values.location } },
      })
      const account = services.session.adoptAccount(data.user, epoch)
      const next = { username: account.username, bio: account.profile.bio || '', location: account.profile.location || '' }
      setValues(next); setSaved(next)
    }, 'Profile saved.')
  }
  return <section className="page-section"><div className="page-heading"><p className="eyebrow">Private profile and settings</p><h1>A little more you.</h1></div>
    <Card className="profile-card"><Initials name={user.username} /><div><h2>{user.username}</h2><p>{user.email}</p></div><span className="pill">Only visible to you</span></Card>
    <div className="settings-grid"><Card><h2>Profile settings</h2><p>Your email is read-only. Email changes and account deletion are not available.</p>
      <ActionFeedback action={action} />
      <form method="post" className="form-stack" aria-label="Profile settings" onSubmit={event => { void save(event) }}>
        <fieldset disabled={action.busy} className="form-stack"><legend className="sr-only">Editable account fields</legend>
          <Field label="Username" autoComplete="username" required maxLength={50} value={values.username} error={action.error?.fieldErrors.username} onChange={event => setValues({ ...values, username: event.target.value })} />
          <TextareaField id="profile-bio" label="Bio" maxLength={2000} rows={5} value={values.bio} error={action.error?.fieldErrors['profile.bio']} onChange={event => setValues({ ...values, bio: event.target.value })} />
          <Field label="Location" autoComplete="address-level2" maxLength={100} value={values.location} error={action.error?.fieldErrors['profile.location']} onChange={event => setValues({ ...values, location: event.target.value })} />
          <div className="action-row"><Button type="submit" pending={action.busy}>Save profile</Button>
            <Button variant="quiet" type="button" onClick={() => { setValues(saved); action.clear() }}>Discard profile changes</Button></div>
        </fieldset>
      </form>
    </Card><PasswordChange profileDirty={dirty} /></div>
  </section>
}
function PasswordChange({ profileDirty }: { profileDirty: boolean }) {
  const { session } = useServices()
  const navigate = useNavigate()
  const action = useAction()
  const form = useRef<HTMLFormElement>(null)
  const [confirmationError, setConfirmationError] = useState<string[] | undefined>()
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (profileDirty || action.busy) return
    const data = new FormData(event.currentTarget)
    const password = String(data.get('new_password') || '')
    if (password !== data.get('confirmation')) { setConfirmationError(['The new passwords do not match.']); (form.current?.elements.namedItem('confirmation') as HTMLInputElement | null)?.focus(); return }
    setConfirmationError(undefined)
    await action.run(async () => {
      try {
        await session.changePassword(String(data.get('current_password') || ''), password)
        navigate('/login', { replace: true, state: { accountNotice: 'Password changed. All earlier sessions were revoked. Sign in with your new password.' } })
      } catch (error) {
        if (session.getSnapshot().status === 'anonymous') navigate('/login', { replace: true, state: {
          accountNotice: 'The password change was interrupted and its outcome is unconfirmed. You are signed out on this page; existing server sessions may still be active. Try signing in with your current or new password.',
        } })
        throw error
      } finally { form.current?.reset() }
    })
  }
  return <Card><h2>Change password</h2><p>A successful change signs you out and revokes your earlier sessions. You will need to sign in again.</p>
    {profileDirty && <Feedback>Save or discard your profile changes before changing your password.</Feedback>}
    <ActionFeedback action={action} />
    <form ref={form} method="post" className="form-stack" aria-label="Change password" onSubmit={event => { void submit(event) }}>
      <fieldset disabled={action.busy || profileDirty} className="form-stack"><legend className="sr-only">Password verification</legend>
        <Field label="Current password" name="current_password" type="password" required maxLength={1024} autoComplete="current-password" error={action.error?.fieldErrors.current_password} />
        <Field label="New password" name="new_password" type="password" required minLength={8} maxLength={1024} autoComplete="new-password" error={action.error?.fieldErrors.new_password} hint="Use a strong, unique password. Django validates it against your account." />
        <Field label="Confirm new password" name="confirmation" type="password" required minLength={8} maxLength={1024} autoComplete="new-password" error={confirmationError} />
        <Button type="submit" pending={action.busy}>Change password and sign out</Button>
      </fieldset>
    </form>
    <p><Link to="/forgot-password">Password recovery availability</Link></p>
  </Card>
}
export function RecoveryUnavailable() {
  return <section className="page-section"><Card><p className="eyebrow">Account recovery</p>
    <h1>Password recovery is not available yet.</h1>
    <Feedback>Reset emails cannot be sent while recovery is unavailable. No reset credentials are accepted on this page.</Feedback>
    <p>If you can sign in, change your password in your private account settings.</p>
    <Link className="button button--primary" to="/login">Return to sign in</Link>
  </Card></section>
}
