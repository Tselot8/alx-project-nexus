import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { expect, test } from '@playwright/test'
import type { BrowserContext, Page } from '@playwright/test'
import type { PollDetail, SessionResponse } from '../src/api/contracts'
import { create, credentials, localOnly, register, transition } from './helpers'

const axeSource = readFileSync(createRequire(import.meta.url).resolve('axe-core/axe.min.js'), 'utf8')
test.setTimeout(120_000)

async function audit(page: Page, label: string) {
  await test.step('accessibility and reflow: ' + label, async () => {
    try { await expect(page.locator('.loading')).toHaveCount(0) }
    catch (error) {
      test.info().annotations.push({ type: 'qa-state', description: JSON.stringify({
        loading: await page.locator('.loading').count(), visibleLoading: await page.locator('.loading:visible').count(),
        reviewButtons: await page.getByRole('button', { name: 'Review & publish' }).count(),
      }) })
      throw error
    }
    await page.addScriptTag({ content: axeSource })
    const results = await page.evaluate(async () => {
      const axe = (window as unknown as { axe: typeof import('axe-core') }).axe
      const report = await axe.run(document, {
        runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa', 'best-practice'] },
      })
      // Never export DOM HTML, input values, or credentials in diagnostics.
      return report.violations.map(item => ({ id: item.id, impact: item.impact, nodes: item.nodes.length }))
    })
    if (results.length) test.info().annotations.push({ type: 'qa-rules', description: JSON.stringify(results) })
    expect(results).toEqual([])
    const overflow = await page.evaluate(() => Array.from(document.querySelectorAll('*')).filter(element => {
      const rect = element.getBoundingClientRect()
      return rect.right > innerWidth + 1 && rect.width > 0
    }).map(element => ({ tag: element.tagName, className: element.className, width: Math.round(element.getBoundingClientRect().width) })).slice(0, 15))
    if (overflow.length) test.info().annotations.push({ type: 'qa-overflow', description: JSON.stringify(overflow) })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
  })
}
async function visit(page: Page, path: string, label = path) {
  await page.goto(path)
  await expect(page.getByRole('main').getByRole('heading', { level: 1 })).toBeVisible()
  await audit(page, label)
}
async function apiOwner(context: BrowserContext, base: string) {
  const csrf = await context.request.get('/api/v2/auth/csrf/')
  expect(csrf.status()).toBe(200)
  const bootstrap = await csrf.json() as { csrf_token: string }
  const response = await context.request.post('/api/v2/auth/register/', {
    headers: { Origin: base, 'X-CSRFToken': bootstrap.csrf_token }, data: credentials('qa'),
  })
  expect(response.status()).toBe(201)
  return await response.json() as SessionResponse
}
async function apiPoll(context: BrowserContext, owner: SessionResponse, data: Record<string, unknown>) {
  const headers = { Authorization: 'Bearer ' + owner.access }
  const created = await context.request.post('/api/v2/polls/', { headers, data })
  expect(created.status()).toBe(201)
  const draft = await created.json() as PollDetail
  const published = await context.request.post('/api/v2/polls/' + draft.id + '/publish/', { headers, data: {} })
  expect(published.status()).toBe(200)
  return await published.json() as PollDetail
}

test('guest routes meet automated AA, reflow, keyboard and reduced-motion checks', async ({ page, browser, baseURL, context }) => {
  await localOnly(context, baseURL!)
  const creator = await browser.newContext({ baseURL: baseURL! })
  let privateLink: string
  let publicPoll: PollDetail
  try {
    const owner = await apiOwner(creator, baseURL!)
    publicPoll = await apiPoll(creator, owner, {
      question: 'A long public question ' + 'unbrokenword'.repeat(16),
      description: 'Responsive and accessibility verification.',
      options: [{ option_text: 'Alternative ' + 'unbrokenchoice'.repeat(15) }, { option_text: 'Another answer' }],
    })
    const privatePoll = await apiPoll(creator, owner, {
      question: 'QA private reading', visibility: 'private',
      options: [{ option_text: 'Yes' }, { option_text: 'No' }],
    })
    const issued = await creator.request.post('/api/v2/polls/' + privatePoll.id + '/share/', {
      headers: { Authorization: 'Bearer ' + owner.access }, data: {},
    })
    expect(issued.status()).toBe(201)
    const secret = await issued.json() as { token: string }
    privateLink = baseURL + '/polls/' + privatePoll.id + '#share=' + secret.token
  } finally { await creator.close() }
  await visit(page, '/', 'home with real public card')
  const skip = page.getByRole('link', { name: 'Skip to content' })
  for (let step = 0; step < 12; step++) {
    await page.keyboard.press('Shift+Tab')
    if (await skip.evaluate(element => element === document.activeElement)) break
  }
  await expect(skip).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('main')).toBeFocused()
  for (const path of ['/polls', '/login', '/register', '/forgot-password', '/reset-password', '/not-found']) await visit(page, path)
  await visit(page, '/polls/' + publicPoll!.id, 'public detail, zero results and long options')
  const viewport = page.viewportSize()
  if (viewport?.width === 390) {
    await page.setViewportSize({ width: 320, height: 844 })
    await audit(page, '320 CSS-pixel reflow with long options and results table')
    await page.setViewportSize(viewport)
  }
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.evaluate(() => { document.documentElement.style.fontSize = '200%' })
  await audit(page, '200 percent text scaling')
  await page.evaluate(() => { document.documentElement.style.fontSize = '' })
  await page.goto(privateLink)
  await expect(page.getByRole('heading', { name: 'QA private reading' })).toBeVisible()
  expect(new URL(page.url()).hash).toBe('')
  await audit(page, 'guest private reading and authorized results')
  await page.reload()
  await expect(page.getByRole('heading', { name: "We couldn't open this poll." })).toBeVisible()
  await audit(page, 'private unavailable state')
})

test('creator forms, confirmations, single-choice voting and recovery from transport failures remain accessible', async ({ page, context, baseURL }) => {
  await localOnly(context, baseURL!)
  await register(page, credentials('qa_creator'))
  await audit(page, 'empty My polls')
  await visit(page, '/profile')
  await visit(page, '/polls/new')
  await page.getByRole('button', { name: 'Review & publish' }).click()
  await expect(page.getByRole('alert').first()).toBeVisible()
  await audit(page, 'publication validation errors')
  const poll = await create(page, { privatePoll: true })
  await audit(page, 'draft management')
  await page.getByRole('button', { name: 'Publish poll', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Publish this poll?' })).toBeFocused()
  await audit(page, 'publish confirmation')
  await page.keyboard.press('Tab')
  await expect(page.getByRole('button', { name: 'Confirm publish' })).toBeFocused()
  await page.keyboard.press('Tab')
  await page.keyboard.press('Enter')
  await expect(page.getByRole('button', { name: 'Publish poll', exact: true })).toBeFocused()
  await transition(page, 'publish')
  await page.getByRole('button', { name: 'Issue private link' }).click()
  await expect(page.getByLabel(/New private link/)).toBeVisible()
  await audit(page, 'one-time private sharing controls')
  await page.getByRole('button', { name: 'Regenerate link' }).click()
  await expect(page.getByRole('heading', { name: 'Replace the current private link?' })).toBeFocused()
  await page.getByRole('button', { name: 'Cancel', exact: true }).click()
  await visit(page, poll.detail, 'creator ballot and aggregate results')
  await page.getByRole('radio', { name: /Morning/ }).focus()
  await page.keyboard.press(' ')
  await page.keyboard.press('ArrowDown')
  await expect(page.getByRole('radio', { name: /Afternoon/ })).toBeChecked()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('button', { name: 'Submit vote' })).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.getByText('Your vote was saved.', { exact: true })).toBeVisible()
  await audit(page, 'saved single-choice ballot and results table')
  if ((page.viewportSize()?.width || 0) <= 832) {
    await page.getByRole('button', { name: 'Menu', exact: true }).click()
    await page.keyboard.press('Tab')
    await expect(page.getByRole('navigation', { name: 'Mobile' }).getByRole('link', { name: 'Home', exact: true })).toBeFocused()
    await page.keyboard.press('Escape')
    await expect(page.getByRole('button', { name: 'Menu', exact: true })).toBeFocused()
  }
  let unavailable = true
  let release!: () => void
  const waiting = new Promise<void>(resolve => { release = resolve })
  await context.route('**/api/v2/polls/?*', async route => {
    if (unavailable) { await waiting; await route.abort('failed') } else await route.continue()
  })
  await page.goto('/polls')
  try {
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await expect(page.getByText(/^Loading public polls/)).toBeVisible()
    await expect(page.locator('.loading').filter({ hasText: /^Loading public polls/ }).locator('.spinner')).toHaveCSS('animation-name', 'none')
  } finally { release() }
  await expect(page.getByRole('button', { name: 'Retry polls' })).toBeVisible()
  await audit(page, 'live API transport failure feedback')
  unavailable = false
  await page.getByRole('button', { name: 'Retry polls' }).click()
  await expect(page.getByRole('heading', { name: 'No polls found' })).toBeVisible()
  await audit(page, 'empty discovery after successful retry')
})
