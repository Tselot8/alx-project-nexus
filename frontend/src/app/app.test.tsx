import { StrictMode } from 'react'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import axe from 'axe-core'
import { App } from './app'
import { Providers } from './providers'
import { createServices } from './services'
import { AppErrorBoundary } from './error-boundary'
import { safeReturnTo } from '../auth/navigation'
import { alice, anonymousNetwork, failure, json, network, pollId, sessionData } from '../test/network'

function renderApp(path = '/', services = createServices()) {
  return { services, ...render(<StrictMode><Providers services={services}>
    <MemoryRouter initialEntries={[path]}><App /></MemoryRouter>
  </Providers></StrictMode>) }
}
describe('routes and the accessible application shell', () => {
  it.each([
    ['/', 'Different voices.'],
    ['/polls', 'A good question is a great beginning.'],
    ['/polls/' + pollId, 'When should our community meet?'],
    ['/login', 'Welcome back to Nexus.'],
    ['/register', 'Every voice starts somewhere.'],
    ['/missing', 'This page isn’t here.'],
  ])('renders the intended public page at %s', async (path, title) => {
    anonymousNetwork()
    renderApp(path)
    expect(await screen.findByRole('heading', { level: 1, name: new RegExp(title.replaceAll('.', '[.]')) })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Skip to content' })).toHaveAttribute('href', '#main-content')
  })
  it.each(['/my-polls', '/polls/new', '/profile'])('protects %s and retains a safe return destination', async path => {
    anonymousNetwork()
    renderApp(path)
    expect(await screen.findByRole('heading', { level: 1, name: 'Welcome back to Nexus.' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Create an account' })).toHaveAttribute('href', '/register?returnTo=' + encodeURIComponent(path))
  })
  it('uses the static create route rather than treating new as a poll ID', async () => {
    network(path => {
      if (path.endsWith('/refresh/')) return json({ access: 'test-access', expires_in: 300 })
      if (path.endsWith('/me/')) return json({ user: alice })
      return json({ csrf_token: 'test-csrf' })
    })
    renderApp('/polls/new')
    expect(await screen.findByRole('heading', { level: 1, name: 'What would you like to ask?' })).toBeInTheDocument()
    expect(screen.getByText('This preview cannot create or save a poll.', { exact: false })).toBeInTheDocument()
  })
  it('bootstraps only once under StrictMode', async () => {
    const fetcher = anonymousNetwork()
    renderApp('/')
    await waitFor(() => expect(fetcher.mock.calls.filter(([path]) => String(path).includes('/auth/'))).toHaveLength(2))
    expect(fetcher.mock.calls.filter(([path]) => String(path).endsWith('/refresh/'))).toHaveLength(1)
  })
  it('supports menu disclosure, Escape focus return and navigation closing', async () => {
    anonymousNetwork()
    const user = userEvent.setup()
    renderApp()
    const toggle = screen.getByRole('button', { name: 'Menu' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    await user.click(toggle)
    const nav = screen.getByRole('navigation', { name: 'Mobile' })
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    await user.keyboard('{Escape}')
    expect(toggle).toHaveFocus()
    expect(nav).not.toBeVisible()
    await user.click(toggle)
    await user.click(within(nav).getByRole('link', { name: 'Explore polls' }))
    expect(await screen.findByRole('heading', { level: 1, name: 'A good question is a great beginning.' })).toBeInTheDocument()
    expect(nav).not.toBeVisible()
    expect(document.getElementById('main-content')).toHaveFocus()
  })
  it('checks home semantics with axe without claiming visual contrast certification', async () => {
    anonymousNetwork()
    renderApp()
    await screen.findByRole('heading', { level: 1 })
    document.documentElement.lang = 'en'
    const result = await axe.run(document.body, {
      runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'] },
      rules: { 'color-contrast': { enabled: false } },
    })
    expect(result.violations.map(row => row.id)).toEqual([])
  })
  it('shows a recoverable session failure instead of redirecting to login on an outage', async () => {
    network(() => { throw new TypeError('offline') })
    renderApp('/profile')
    expect(await screen.findByRole('button', { name: 'Retry session check' })).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('could not verify your session')
  })
  it('shows a generic error boundary without exposing the thrown error', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    function Broken(): never { throw new Error('test-internal-debug-details') }
    render(<AppErrorBoundary><Broken /></AppErrorBoundary>)
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Something interrupted this page.')
    expect(screen.queryByText('test-internal-debug-details')).not.toBeInTheDocument()
  })
})
describe('account forms and cache isolation', () => {
  it('signs in and returns to the protected original page without caching credentials', async () => {
    network(path => {
      if (path.endsWith('/refresh/')) return failure(401)
      if (path.endsWith('/login/')) return json(sessionData())
      return json({ csrf_token: 'test-csrf' })
    })
    const user = userEvent.setup()
    const { services } = renderApp('/my-polls')
    await screen.findByRole('heading', { level: 1, name: 'Welcome back to Nexus.' })
    await user.type(screen.getByLabelText('Email address'), alice.email)
    await user.type(screen.getByLabelText('Password'), 'test-only-password')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('heading', { name: 'Good questions start with you.' })).toBeInTheDocument()
    expect(services.queryClient.getMutationCache().getAll()).toEqual([])
    expect(services.queryClient.getQueryCache().getAll()).toEqual([])
  })
  it('registers and renders the private current-user profile', async () => {
    network(path => {
      if (path.endsWith('/refresh/')) return failure(401)
      if (path.endsWith('/register/')) return json(sessionData(), 201)
      return json({ csrf_token: 'test-csrf' })
    })
    const user = userEvent.setup()
    renderApp('/register?returnTo=%2Fprofile')
    await user.type(screen.getByLabelText('Username'), 'Alice')
    await user.type(screen.getByLabelText('Email address'), alice.email)
    await user.type(screen.getByLabelText('Password'), 'test-only-password')
    await user.click(screen.getByRole('button', { name: 'Create account' }))
    expect(await screen.findByRole('heading', { level: 1, name: 'A little more you.' })).toBeInTheDocument()
    expect(screen.getByText(alice.email)).toBeInTheDocument()
    expect(screen.getByText('Only visible to you')).toBeInTheDocument()
  })
  it('associates backend validation errors with the relevant registration field', async () => {
    network(path => {
      if (path.endsWith('/refresh/')) return failure(401)
      if (path.endsWith('/register/')) return failure(400, { password: ['This password is too common.'] }, 'invalid')
      return json({ csrf_token: 'test-csrf' })
    })
    const user = userEvent.setup()
    renderApp('/register')
    await user.type(screen.getByLabelText('Username'), 'Alice')
    await user.type(screen.getByLabelText('Email address'), alice.email)
    await user.type(screen.getByLabelText('Password'), 'test-only-password')
    await user.click(screen.getByRole('button', { name: 'Create account' }))
    await screen.findByText('This password is too common.')
    expect(screen.getByLabelText('Password')).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByLabelText('Password')).toHaveAccessibleDescription(/This password is too common[.]/)
  })
  it('clears private query data and current-user UI on logout', async () => {
    network(path => {
      if (path.endsWith('/login/')) return json(sessionData())
      if (path.endsWith('/logout/')) return json(null, 204)
      return json({ csrf_token: 'test-csrf' })
    })
    const services = createServices()
    await services.session.login({ email: alice.email, password: 'test-only-password' })
    services.queryClient.setQueryData(['private', alice.id], { sensitive: true })
    const user = userEvent.setup()
    renderApp('/profile', services)
    await user.click(screen.getByRole('button', { name: 'Sign out' }))
    await waitFor(() => expect(services.session.getSnapshot().status).toBe('anonymous'))
    expect(services.queryClient.getQueryCache().getAll()).toHaveLength(0)
    expect(screen.queryByText(alice.email)).not.toBeInTheDocument()
  })
  it.each(['https://evil.example.invalid/', '//evil.example.invalid', '/\\evil.example.invalid',
    '/my-polls#share=secret', '/api/v2/auth/logout/', '/login', '/polls/%2f%2fevil'])(
    'rejects unsafe return navigation %s', value => { expect(safeReturnTo(value)).toBe('/my-polls') })
  it('drops query strings and fragments from return navigation', async () => {
    expect(safeReturnTo('/profile?token=test-only-secret')).toBe('/profile')
    await act(async () => { expect(safeReturnTo('/polls/new')).toBe('/polls/new') })
  })
})
