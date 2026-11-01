import { randomBytes } from 'node:crypto'
import { expect } from '@playwright/test'
import type { BrowserContext, Page } from '@playwright/test'
export const credentials = (role: string) => {
  const name = role + '_' + randomBytes(4).toString('hex')
  return { username: name, email: name + '@example.invalid', password: 'Nexus!' + randomBytes(24).toString('hex') }
}
export async function localOnly(context: BrowserContext, base: string) {
  await context.route('**/*', route => new URL(route.request().url()).origin === base ? route.continue() : route.abort())
}
export async function register(page: Page, user = credentials('browser')) {
  await page.goto('/register')
  await page.getByLabel('Username', { exact: true }).fill(user.username)
  await page.getByLabel('Email address').fill(user.email)
  await page.getByLabel('Password', { exact: true }).fill(user.password)
  await page.getByRole('button', { name: 'Create account' }).click()
  await expect(page).toHaveURL(/\/my-polls$/)
  return user
}
export async function login(page: Page, user: ReturnType<typeof credentials>) {
  await page.goto('/login')
  await page.getByLabel('Email address').fill(user.email)
  await page.getByLabel('Password', { exact: true }).fill(user.password)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page).toHaveURL(/\/my-polls$/)
}
export async function create(page: Page, { privatePoll = false, multiple = false } = {}) {
  const question = 'Browser question ' + randomBytes(4).toString('hex')
  await page.goto('/polls/new')
  await page.getByLabel('Question', { exact: true }).fill(question)
  await page.getByLabel('Description (optional)').fill('Live browser integration')
  if (privatePoll) await page.getByLabel('Visibility', { exact: true }).selectOption('private')
  if (multiple) {
    await page.getByLabel('Voting mode').selectOption('multiple')
    await page.getByLabel('Minimum selections').fill('1')
    await page.getByLabel('Maximum selections').fill('2')
  }
  await page.getByLabel('Results visibility').selectOption(privatePoll ? 'immediate' : 'after_voting')
  await page.getByLabel('Category', { exact: true }).selectOption({ label: 'Browser topics' })
  await page.getByLabel('Option 1', { exact: true }).fill('Morning')
  await page.getByLabel('Option 2', { exact: true }).fill('Afternoon')
  await page.getByRole('button', { name: 'Save draft', exact: true }).click()
  await expect(page).toHaveURL(/\/polls\/[a-f0-9-]+\/manage$/)
  const path = new URL(page.url()).pathname
  return { question, manage: path, detail: path.replace('/manage', '') }
}
export async function transition(page: Page, action: 'publish' | 'close' | 'reopen' | 'archive') {
  const label = { publish: 'Publish poll', close: 'Close poll', reopen: 'Reopen poll', archive: 'Archive poll' }[action]
  await page.getByRole('button', { name: label, exact: true }).click()
  if (action === 'reopen') await page.getByLabel('Reopen with no expiration').check()
  await page.getByRole('button', { name: 'Confirm ' + action, exact: true }).click()
  await expect(page.getByText({ publish: 'Poll published.', close: 'Poll closed.', reopen: 'Poll reopened.', archive: 'Poll archived.' }[action], { exact: true })).toBeVisible()
}
export async function noStoredSecrets(page: Page) {
  const state = await page.evaluate(() => ({
    local: localStorage.length, session: sessionStorage.length,
    cookieReadable: document.cookie.includes('nexus_v2_refresh_token'),
  }))
  expect(state).toEqual({ local: 0, session: 0, cookieReadable: false })
}
