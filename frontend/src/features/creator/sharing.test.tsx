import { act, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { failure, json, pollId } from '../../test/network'
import { authenticatedApp, fixture, writes } from './test-fixture'

const manage = '/polls/' + pollId + '/manage'
const share = '/api/v2/polls/' + pollId + '/share/'
const secret = 't'.repeat(43)
describe('one-time private sharing', () => {
  it('issues a fragment link once, copies explicitly and never caches/stores the token', async () => {
    const { fetcher, state } = fixture({ visibility: 'private', status: 'published' })
    const { services } = await authenticatedApp(manage)
    const user = userEvent.setup()
    const write = vi.spyOn(Storage.prototype, 'setItem')
    await user.click(await screen.findByRole('button', { name: 'Issue private link' }))
    const field = await screen.findByLabelText('New private link · shown once')
    expect(field).toHaveValue(window.location.origin + '/polls/' + pollId + '#share=' + secret)
    expect(state.active).toBe(true)
    expect(screen.getByRole('button', { name: 'Issue private link' })).toBeDisabled()
    expect(write).not.toHaveBeenCalled()
    expect(services.queryClient.getMutationCache().getAll()).toEqual([])
    const cache = JSON.stringify(services.queryClient.getQueryCache().getAll().map(query => [query.queryKey, query.state.data, query.state.error]))
    expect(cache).not.toContain(secret)
    expect(fetcher.mock.calls.every(([path]) => !String(path).includes(secret))).toBe(true)
    const clipboard = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue()
    await user.click(screen.getByRole('button', { name: 'Copy private link' }))
    expect(clipboard).toHaveBeenCalledWith(window.location.origin + '/polls/' + pollId + '#share=' + secret)
    await screen.findByText('Link copied. Share it only with people you trust.')
    await user.click(screen.getByRole('button', { name: 'Hide private link' }))
    expect(screen.queryByLabelText('New private link · shown once')).not.toBeInTheDocument()
  })
  it('confirms regeneration and revocation without retrieving plaintext', async () => {
    const { state, fetcher } = fixture({ visibility: 'private', status: 'closed' })
    state.active = true
    await authenticatedApp(manage)
    await userEvent.click(await screen.findByRole('button', { name: 'Regenerate link' }))
    expect(writes(fetcher).some(([path]) => path === share + 'regenerate/')).toBe(false)
    await userEvent.click(screen.getByRole('button', { name: 'Replace private link' }))
    await screen.findByLabelText('New private link · shown once')
    expect(state.generation).toBe(2)
    await userEvent.click(screen.getByRole('button', { name: 'Revoke link' }))
    expect(state.active).toBe(true)
    await userEvent.click(screen.getByRole('button', { name: 'Revoke private link' }))
    await waitFor(() => expect(state.active).toBe(false))
    expect(screen.queryByLabelText('New private link · shown once')).not.toBeInTheDocument()
    expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'GET').every(([, init]) => !String(init?.body).includes(secret))).toBe(true)
  })
  it('does not reconstruct an existing active token after reload', async () => {
    const { state } = fixture({ visibility: 'private', status: 'published' })
    state.active = true
    await authenticatedApp(manage)
    await screen.findByText('A private link is active.')
    expect(screen.queryByLabelText('New private link · shown once')).not.toBeInTheDocument()
    expect(screen.getByText(/Only a newly issued link can be displayed/)).toBeInTheDocument()
  })
  it('hides one-time link material when the server reports a new generation', async () => {
    const { state } = fixture({ visibility: 'private', status: 'published' })
    const { services } = await authenticatedApp(manage)
    await userEvent.click(await screen.findByRole('button', { name: 'Issue private link' }))
    await screen.findByLabelText('New private link · shown once')
    state.generation++
    await act(async () => services.queryClient.refetchQueries({ queryKey: ['poll-share'] }))
    await waitFor(() => expect(screen.queryByLabelText('New private link · shown once')).not.toBeInTheDocument())
  })
  it.each(['draft', 'archived'] as const)('never offers issuance/regeneration for %s', async status => {
    const { state } = fixture({ visibility: 'private', status })
    if (status === 'archived') state.active = true
    await authenticatedApp(manage)
    await screen.findByRole('heading', { name: 'Private sharing' })
    await waitFor(() => expect(screen.queryByText('Loading sharing status…')).not.toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Issue private link' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Regenerate link' })).not.toBeInTheDocument()
    if (status === 'archived') expect(screen.getByRole('button', { name: 'Revoke link' })).toBeInTheDocument()
  })
  it('does not display a sharing error body that could contain sensitive diagnostics', async () => {
    fixture({ visibility: 'private', status: 'published' }, (path, init) => path === share && init.method === 'POST' ? failure(409, { detail: secret }) : undefined)
    await authenticatedApp(manage)
    await userEvent.click(await screen.findByRole('button', { name: 'Issue private link' }))
    await screen.findByText(/A link is already active/)
    expect(document.body.textContent).not.toContain(secret)
    expect(screen.queryByLabelText('New private link · shown once')).not.toBeInTheDocument()
  })
  it('provides a copy fallback when clipboard permission is denied', async () => {
    fixture({ visibility: 'private', status: 'published' })
    await authenticatedApp(manage)
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Issue private link' }))
    await screen.findByLabelText('New private link · shown once')
    vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValue(new Error('permission denied'))
    await user.click(screen.getByRole('button', { name: 'Copy private link' }))
    expect(await screen.findByText(/Select and copy the link from the field above/)).toBeInTheDocument()
  })
  it('does not load sharing controls for public polls', async () => {
    const { fetcher } = fixture({ visibility: 'public' })
    await authenticatedApp(manage)
    await screen.findByLabelText('Question')
    expect(screen.queryByRole('heading', { name: 'Private sharing' })).not.toBeInTheDocument()
    expect(fetcher.mock.calls.some(([path]) => path === share)).toBe(false)
  })
  it('removes secret UI and creator queries on logout', async () => {
    fixture({ visibility: 'private', status: 'published' })
    const { services } = await authenticatedApp(manage)
    await userEvent.click(await screen.findByRole('button', { name: 'Issue private link' }))
    await screen.findByLabelText('New private link · shown once')
    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    await screen.findByRole('heading', { name: 'Welcome back to Nexus.' })
    expect(screen.queryByLabelText('New private link · shown once')).not.toBeInTheDocument()
    expect(services.queryClient.getQueryCache().getAll()).toEqual([])
  })
})

it('allowlists status metadata so unexpected token material cannot enter a query cache', async () => {
  fixture({ visibility: 'private', status: 'published' }, (path, init) => path === share && init.method === 'GET'
    ? json({ poll_id: pollId, active: false, generation: 1, token: secret }) : undefined)
  const { services } = await authenticatedApp(manage)
  await screen.findByRole('button', { name: 'Issue private link' })
  expect(JSON.stringify(services.queryClient.getQueryCache().getAll().map(query => query.state.data))).not.toContain(secret)
})
it('rejects an issuance response for the wrong poll without displaying its token', async () => {
  fixture({ visibility: 'private', status: 'published' }, (path, init) => path === share && init.method === 'POST'
    ? json({ poll_id: '99999999-9999-4999-8999-999999999999', generation: 2, token: secret }, 201) : undefined)
  const { services } = await authenticatedApp(manage)
  await userEvent.click(await screen.findByRole('button', { name: 'Issue private link' }))
  await screen.findByText(/The sharing change could not be confirmed/)
  expect(screen.queryByLabelText('New private link · shown once')).not.toBeInTheDocument()
  expect(JSON.stringify(services.queryClient.getQueryCache().getAll().map(query => query.state.data))).not.toContain(secret)
})
