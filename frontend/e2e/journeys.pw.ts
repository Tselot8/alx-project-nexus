import { expect, test } from '@playwright/test'
import { create, credentials, localOnly, login, noStoredSecrets, register, transition } from './helpers'

test.beforeEach(async ({ context, baseURL }) => { await localOnly(context, baseURL!) })

test('creator publishes, voter replaces an atomic ballot, results and lifecycle remain consistent', async ({ page, browser, baseURL }) => {
  await test.step('register and restore creator session', async () => {
    await register(page)
    await page.reload()
    await expect(page.getByRole('link', { name: 'My profile' })).toBeVisible()
    await noStoredSecrets(page)
    const cookie = (await page.context().cookies()).find(cookie => cookie.name === 'nexus_v2_refresh_token')
    expect(cookie?.httpOnly).toBe(true)
    expect(cookie?.path).toBe('/api/v2/auth/')
    expect(cookie?.sameSite).toBe('Lax')
    expect(cookie?.secure).toBe(false) // Isolated loopback HTTP only.
  })
  const poll = await test.step('save a configured draft', async () => create(page, { multiple: true }))
  await test.step('add and edit draft options, then publish', async () => {
    await page.getByRole('button', { name: 'Add option', exact: true }).click()
    await page.getByLabel('Option text', { exact: true }).fill('Evening')
    await page.getByRole('button', { name: 'Save option', exact: true }).click()
    await expect(page.getByText('Option saved.', { exact: true })).toBeVisible()
    const row = page.locator('.managed-options li').filter({ hasText: 'Evening' })
    await row.getByRole('button', { name: 'Edit option' }).click()
    await page.getByLabel('Option text', { exact: true }).fill('Late evening')
    await page.getByRole('button', { name: 'Save option', exact: true }).click()
    await expect(page.locator('.managed-options')).toContainText('Late evening')
    await transition(page, 'publish')
  })
  const voter = await browser.newContext({ baseURL: baseURL! })
  await localOnly(voter, baseURL!)
  try {
    const participant = await voter.newPage()
    await test.step('discover the real public poll and sign in', async () => {
      await participant.goto('/polls')
      await participant.getByLabel('Search polls').fill(poll.question)
      await participant.getByRole('button', { name: 'Search', exact: true }).click()
      await participant.getByLabel('Category', { exact: true }).selectOption({ label: 'Browser topics' })
      await participant.getByLabel('Sort by').selectOption('oldest')
      await participant.getByRole('link', { name: poll.question, exact: true }).click()
      await expect(participant.getByRole('table')).toHaveCount(0)
      await expect(participant.getByRole('link', { name: 'Sign in to participate' })).toBeVisible()
      await register(participant, credentials('voter'))
      await participant.goto(poll.detail)
    })
    await test.step('submit a complete multiple-choice set and replace it', async () => {
      await participant.getByRole('checkbox', { name: /Morning/ }).check()
      await participant.getByRole('checkbox', { name: /Late evening/ }).check()
      await expect(participant.getByRole('checkbox', { name: /Afternoon/ })).toBeDisabled()
      await participant.getByRole('button', { name: 'Submit vote', exact: true }).click()
      await expect(participant.getByText('Your vote was saved.', { exact: true })).toBeVisible()
      await expect(participant.getByRole('table')).toBeVisible()
      await expect(participant.getByRole('row', { name: /Morning/ })).toContainText('50%')
      await participant.getByRole('checkbox', { name: /Morning/ }).uncheck()
      await participant.getByRole('button', { name: 'Update vote', exact: true }).click()
      await expect(participant.getByText(/Your ballot was updated/)).toBeVisible()
      await expect(participant.getByRole('row', { name: /Morning/ })).toContainText('0%')
      await expect(participant.getByRole('row', { name: /Late evening/ })).toContainText('100%')
      await noStoredSecrets(participant)
    })
    await test.step('close, reopen explicitly, and archive without accepting further votes', async () => {
      await page.reload()
      await expect(page.getByLabel('Question', { exact: true })).toBeDisabled()
      await transition(page, 'close')
      await participant.reload()
      await expect(participant.getByText(/Voting is closed/)).toBeVisible()
      await expect(participant.getByRole('table')).toBeVisible()
      await transition(page, 'reopen')
      await participant.reload()
      await expect(participant.getByRole('button', { name: 'Update vote' })).toBeDisabled()
      await transition(page, 'archive')
      await participant.reload()
      await expect(participant.getByText(/This poll is archived/)).toBeVisible()
      await expect(participant.getByRole('button', { name: 'Update vote' })).toHaveCount(0)
    })
  } finally { await voter.close() }
})

test('private fragments grant scoped reads, disappear from history, and revoked links fail', async ({ page, browser, baseURL }) => {
  await register(page)
  const poll = await create(page, { privatePoll: true })
  await transition(page, 'publish')
  let link = ''
  await test.step('issue a private link once', async () => {
    await page.getByRole('button', { name: 'Issue private link' }).click()
    link = await page.getByLabel(/New private link/).inputValue()
    expect(new URL(link).hash.startsWith('#share=')).toBe(true)
    await noStoredSecrets(page)
  })
  const guest = await browser.newContext({ baseURL: baseURL! })
  await localOnly(guest, baseURL!)
  try {
    const reader = await guest.newPage()
    let resolutions = 0
    let credentialLeak = false
    reader.on('request', request => {
      const url = new URL(request.url())
      const headers = request.headers()
      if (url.pathname === '/api/v2/shares/resolve/') resolutions++
      if (url.pathname.startsWith('/api/')) {
        const scoped = '/api/v2' + poll.detail + '/'
        if (headers['x-poll-share'] && ![scoped, scoped + 'results/', scoped + 'options/'].includes(url.pathname)) credentialLeak = true
        if ((headers.referer || '').includes('#share=') || url.search.includes('share=')) credentialLeak = true
        if (!url.pathname.startsWith('/api/v2/auth/') && (headers.cookie || '').includes('nexus_v2_refresh_token=')) credentialLeak = true
      }
    })
    await test.step('open shared detail without voting or persistent credentials', async () => {
      await reader.goto(link)
      await expect(reader.getByRole('heading', { name: poll.question, exact: true })).toBeVisible()
      expect(new URL(reader.url()).hash).toBe('')
      await expect(reader.getByText(/Only the creator can vote on private polls/)).toBeVisible()
      await expect(reader.getByRole('table')).toBeVisible()
      await noStoredSecrets(reader)
      await reader.reload()
      await expect(reader.getByRole('heading', { name: "We couldn't open this poll." })).toBeVisible()
      await reader.goto(link)
      try {
        await expect(reader.getByRole('heading', { name: poll.question, exact: true })).toBeVisible()
      } catch (error) {
        const state = await reader.evaluate(() => ({ hasFragment: location.hash.startsWith('#share='), unavailable: document.body.textContent?.includes("We couldn't open this poll."), checking: document.body.textContent?.includes('Checking your private link') }))
        test.info().annotations.push({ type: 'share-state', description: JSON.stringify({ ...state, resolutions }) })
        throw error
      }
    })
    await test.step('regenerate then revoke, rejecting earlier links', async () => {
      await page.getByRole('button', { name: 'Regenerate link' }).click()
      await page.getByRole('button', { name: 'Replace private link', exact: true }).click()
      const current = await page.getByLabel(/New private link/).inputValue()
      // Never include either credential in assertion diagnostics.
      expect(current !== link).toBe(true)
      await reader.goto(link)
      await expect(reader.getByRole('heading', { name: "We couldn't open this poll." })).toBeVisible()
      await reader.goto(current)
      await expect(reader.getByRole('heading', { name: poll.question, exact: true })).toBeVisible()
      await page.getByRole('button', { name: 'Revoke link', exact: true }).click()
      await page.getByRole('button', { name: 'Revoke private link', exact: true }).click()
      await expect(page.getByText('Private link revoked.', { exact: true })).toBeVisible()
      await reader.goto(current)
      await expect(reader.getByRole('heading', { name: "We couldn't open this poll." })).toBeVisible()
      expect(credentialLeak).toBe(false)
    })
  } finally { await guest.close() }
})

test('profile updates and password changes revoke prior browser sessions, then logout restores no identity', async ({ page, browser, baseURL }) => {
  const user = await register(page, credentials('account'))
  const old = await browser.newContext({ baseURL: baseURL! })
  await localOnly(old, baseURL!)
  try {
    const oldPage = await old.newPage()
    await test.step('authenticate an independent prior session', async () => { await login(oldPage, user) })
    await test.step('update profile and change password through the real API', async () => {
      await page.goto('/profile')
      await page.getByLabel('Bio', { exact: true }).fill('Verified in a real browser')
      await page.getByLabel('Location', { exact: true }).fill('Isolated local stack')
      await page.getByRole('button', { name: 'Save profile' }).click()
      await expect(page.getByText('Profile saved.', { exact: true })).toBeVisible()
      const next = credentials('next').password
      await page.getByLabel('Current password', { exact: true }).fill(user.password)
      await page.getByLabel('New password', { exact: true }).fill(next)
      await page.getByLabel('Confirm new password', { exact: true }).fill(next)
      await page.getByRole('button', { name: 'Change password and sign out' }).click()
      await expect(page).toHaveURL(/\/login$/)
      await expect(page.getByText(/All earlier sessions were revoked/)).toBeVisible()
      await oldPage.reload()
      await expect(oldPage).toHaveURL(/\/login\?returnTo=/)
      await expect(oldPage.getByRole('link', { name: 'My profile' })).toHaveCount(0)
      user.password = next
    })
    await test.step('log in with the new password, logout, then reload', async () => {
      await login(page, user)
      await page.getByRole('button', { name: 'Sign out', exact: true }).click()
      await expect(page).toHaveURL(/\/login\?returnTo=/)
      await page.reload()
      await expect(page.getByRole('link', { name: 'My profile' })).toHaveCount(0)
      await noStoredSecrets(page)
    })
  } finally { await old.close() }
})
