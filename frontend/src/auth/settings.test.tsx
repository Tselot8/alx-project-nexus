import { fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import axe from 'axe-core'
import { discardRecoveryCredentials } from './navigation'
import { createServices } from '../app/services'
import { alice, bob, deferred, failure, json, sessionData } from '../test/network'
import { authenticatedApp, fixture } from '../features/creator/test-fixture'

describe('private profile and password settings', () => {
  it('updates only allowed fields and adopts sanitized account state', async () => {
    const { fetcher } = fixture()
    const { services } = await authenticatedApp('/profile')
    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'Alice Updated' } })
    fireEvent.change(screen.getByLabelText('Bio'), { target: { value: 'A short bio' } })
    fireEvent.change(screen.getByLabelText('Location'), { target: { value: 'Addis Ababa' } })
    await userEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    await screen.findByText('Profile saved.')
    const update = fetcher.mock.calls.find(([path, init]) => String(path).endsWith('/me/') && init?.method === 'PATCH')
    expect(JSON.parse(String(update?.[1]?.body))).toEqual({ username: 'Alice Updated', profile: { bio: 'A short bio', location: 'Addis Ababa' } })
    expect(services.session.getSnapshot()).toMatchObject({ status: 'authenticated', user: { username: 'Alice Updated' } })
    expect(screen.queryByLabelText('Email address')).not.toBeInTheDocument()
    expect(services.queryClient.getMutationCache().getAll()).toEqual([])
  })
  it('maps nested profile validation to accessible field errors and preserves edits', async () => {
    fixture({}, (path, init) => String(path).endsWith('/me/') && init.method === 'PATCH' ? failure(400, { profile: { bio: ['Bio is not valid.'] } }) : undefined)
    await authenticatedApp('/profile')
    fireEvent.change(screen.getByLabelText('Bio'), { target: { value: 'Keep my input' } })
    await userEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    await screen.findByRole('alert')
    expect(screen.getByLabelText('Bio')).toHaveValue('Keep my input')
    expect(screen.getByLabelText('Bio')).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByLabelText('Bio')).toHaveAccessibleDescription('Bio is not valid.')
  })
  it('allows discarding profile changes and blocks a password change while they are unsaved', async () => {
    fixture()
    await authenticatedApp('/profile')
    fireEvent.change(screen.getByLabelText('Bio'), { target: { value: 'Unsaved' } })
    expect(screen.getByRole('button', { name: 'Change password and sign out' })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: 'Discard profile changes' }))
    expect(screen.getByLabelText('Bio')).toHaveValue('')
    expect(screen.getByRole('button', { name: 'Change password and sign out' })).toBeEnabled()
  })
  it('rejects password confirmation mismatch without a request', async () => {
    const { fetcher } = fixture()
    await authenticatedApp('/profile')
    fillPasswords('current-password', 'New strong password 8!', 'Different password 9!')
    await userEvent.click(screen.getByRole('button', { name: 'Change password and sign out' }))
    expect(screen.getByLabelText('Confirm new password')).toHaveAccessibleDescription('The new passwords do not match.')
    expect(fetcher.mock.calls.some(([path]) => String(path).endsWith('/password/change/'))).toBe(false)
  })
  it('changes password with bearer/CSRF protection, clears sessions and never caches passwords', async () => {
    const { fetcher } = fixture()
    const { services } = await authenticatedApp('/profile')
    services.queryClient.setQueryData(['private', alice.id], { sensitive: true })
    fillPasswords()
    await userEvent.click(screen.getByRole('button', { name: 'Change password and sign out' }))
    await screen.findByRole('heading', { name: 'Welcome back to Nexus.' })
    expect(await screen.findByText(/Password changed. All earlier sessions were revoked/)).toBeInTheDocument()
    const request = fetcher.mock.calls.find(([path]) => String(path).endsWith('/password/change/'))!
    expect(JSON.parse(String(request[1]?.body))).toEqual({ current_password: 'current-password', new_password: 'New strong password 8!' })
    expect(new Headers(request[1]?.headers).get('Authorization')).toBe('Bearer fixture-access')
    expect(new Headers(request[1]?.headers).get('X-CSRFToken')).toBe('test-csrf-rotated')
    expect(services.session.getSnapshot()).toEqual({ status: 'anonymous' })
    expect(services.queryClient.getQueryCache().getAll()).toEqual([])
    expect(services.queryClient.getMutationCache().getAll()).toEqual([])
    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
  })
  it('preserves the session after rejected current-password verification and clears password inputs', async () => {
    fixture({}, path => String(path).endsWith('/password/change/') ? failure(400, { current_password: ['The current password is incorrect.'] }) : undefined)
    const { services } = await authenticatedApp('/profile')
    fillPasswords()
    await userEvent.click(screen.getByRole('button', { name: 'Change password and sign out' }))
    await screen.findByRole('alert')
    expect(screen.getByLabelText('Current password')).toHaveAccessibleDescription('The current password is incorrect.')
    expect(screen.getByLabelText('New password')).toHaveValue('')
    expect(services.session.getSnapshot().status).toBe('authenticated')
  })
  it('fails closed when password-change outcome is ambiguous', async () => {
    fixture({}, path => String(path).endsWith('/password/change/') ? failure(503) : undefined)
    const { services } = await authenticatedApp('/profile')
    fillPasswords()
    await userEvent.click(screen.getByRole('button', { name: 'Change password and sign out' }))
    await screen.findByRole('heading', { name: 'Welcome back to Nexus.' })
    expect(screen.getByText(/its outcome is unconfirmed/)).toBeInTheDocument()
    expect(services.session.getSnapshot().status).toBe('anonymous')
  })
  it('does not revive a session through refresh queued behind password revocation', async () => {
    const pending = deferred<Response>()
    const { fetcher } = fixture({}, path => String(path).endsWith('/password/change/') ? pending.promise : undefined)
    const services = createServices()
    await services.session.login({ email: alice.email, password: 'fixture-password' })
    const change = services.session.changePassword('old', 'new')
    await waitFor(() => expect(fetcher.mock.calls.some(([path]) => String(path).endsWith('/password/change/'))).toBe(true))
    const refresh = services.session.refresh()
    const rejected = expect(refresh).rejects.toMatchObject({ name: 'AbortError' })
    pending.resolve(json(null, 204))
    await change
    await rejected
    expect(services.session.getSnapshot().status).toBe('anonymous')
    expect(fetcher.mock.calls.some(([path]) => String(path).endsWith('/refresh/'))).toBe(false)
  })
  it('rejects stale account adoption after an identity switch', async () => {
    fixture({}, path => String(path).endsWith('/login/') ? json(sessionData('other-access', bob)) : undefined)
    const services = createServices()
    await services.session.login({ email: bob.email, password: 'fixture' })
    const epoch = services.session.generation
    await services.session.logout()
    expect(() => services.session.adoptAccount(alice, epoch)).toThrow()
    expect(services.session.getSnapshot()).toEqual({ status: 'anonymous' })
  })
  it.each(['/forgot-password', '/reset-password'])('does not pretend disabled recovery works at %s', async path => {
    const { fetcher } = fixture()
    await authenticatedApp(path)
    expect(screen.getByRole('heading', { name: 'Password recovery is not available yet.' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /send|reset/i })).not.toBeInTheDocument()
    expect(fetcher.mock.calls.some(([request]) => String(request).includes('/password/reset/'))).toBe(false)
  })
})
function fillPasswords(current = 'current-password', next = 'New strong password 8!', confirmation = next) {
  fireEvent.change(screen.getByLabelText('Current password'), { target: { value: current } })
  fireEvent.change(screen.getByLabelText('New password'), { target: { value: next } })
  fireEvent.change(screen.getByLabelText('Confirm new password'), { target: { value: confirmation } })
}

it('does not overwrite a confirmed account update with a stale in-flight me response', async () => {
  const pending = deferred<Response>()
  const { fetcher } = fixture({}, path => {
    if (path.endsWith('/refresh/')) return json({ access: 'rotated-access', expires_in: 300 })
    if (path.endsWith('/me/')) return pending.promise
    return undefined
  })
  const services = createServices()
  await services.session.login({ email: alice.email, password: 'fixture' })
  const refreshing = services.session.refresh()
  await waitFor(() => expect(fetcher.mock.calls.some(([path]) => String(path).endsWith('/me/'))).toBe(true))
  services.session.adoptAccount({ ...alice, username: 'Most recent name' }, services.session.generation)
  pending.resolve(json({ user: alice }))
  await refreshing
  expect(services.session.getSnapshot()).toMatchObject({ user: { username: 'Most recent name' } })
})
it('sanitizes adopted account data and refuses adopting another user under the same epoch', async () => {
  fixture()
  const services = createServices()
  await services.session.login({ email: alice.email, password: 'fixture' })
  services.session.adoptAccount({ ...alice, auth_version: 44, is_staff: true, access: 'never-in-state' }, services.session.generation)
  expect(JSON.stringify(services.session.getSnapshot())).not.toMatch(/auth_version|is_staff|never-in-state/)
  expect(() => services.session.adoptAccount(bob, services.session.generation)).toThrow()
})
it('clears disabled reset-link credentials before any account bootstrap', () => {
  window.history.replaceState({}, '', '/reset-password?token=old-query-secret#uid=old&token=old-fragment-secret')
  discardRecoveryCredentials(window)
  expect(window.location.pathname).toBe('/reset-password')
  expect(window.location.hash).toBe('')
  expect(window.location.search).toBe('')
})

it('passes profile/settings accessibility semantics', async () => {
  fixture()
  await authenticatedApp('/profile')
  document.documentElement.lang = 'en'
  const result = await axe.run(document.body, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'] }, rules: { 'color-contrast': { enabled: false } } })
  expect(result.violations.map(row => row.id)).toEqual([])
})
