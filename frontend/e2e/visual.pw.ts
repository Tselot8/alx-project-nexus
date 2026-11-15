import { mkdir } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { expect, test } from '@playwright/test'
import type { BrowserContext, Page } from '@playwright/test'
import type { PollDetail, SessionResponse } from '../src/api/contracts'
import { credentials, localOnly, login, noStoredSecrets, register } from './helpers'

// Only runs through the existing owned, disposable integration stack.
// Screenshots contain synthetic local fixtures, never live accounts or share secrets.
const review = join(tmpdir(), 'nexus-visual-review-20261115')
async function capture(page: Page, name: string) {
  await expect(page.getByRole('main').getByRole('heading', { level: 1 })).toBeVisible()
  await expect(page.locator('.loading')).toHaveCount(0)
  await page.evaluate(async () => {
    await document.fonts.ready
    await Promise.all(Array.from(document.images).map(image => image.decode().catch(() => undefined)))
  })
  await page.evaluate(() => window.scrollTo(0, 0))
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)
  expect(overflow, 'No horizontal document overflow: ' + name).toBe(false)
  await page.screenshot({ path: join(review, name + '.png'), fullPage: true, animations: 'disabled' })
}
async function seed(context: BrowserContext, access: string, data: Record<string, unknown>, publish = true) {
  const headers = { Authorization: 'Bearer ' + access }
  const response = await context.request.post('/api/v2/polls/', { headers, data })
  expect(response.status()).toBe(201)
  const poll = await response.json() as PollDetail
  if (!publish) return poll
  const publication = await context.request.post('/api/v2/polls/' + poll.id + '/publish/', { headers, data: {} })
  expect(publication.status()).toBe(200)
  return await publication.json() as PollDetail
}

test('guest routes and authenticated visual review at five responsive widths', async ({ page, context, browser, baseURL }) => {
  test.setTimeout(240_000)
  await mkdir(review, { recursive: true })
  await localOnly(context, baseURL!)
  const owner = credentials('visual_owner')
  const setup = await browser.newContext({ baseURL: baseURL! })
  let ballot: PollDetail
  let draft: PollDetail
  let reviewCategory: string
  try {
    await localOnly(setup, baseURL!)
    const csrf = await setup.request.get('/api/v2/auth/csrf/')
    const { csrf_token } = await csrf.json() as { csrf_token: string }
    const registration = await setup.request.post('/api/v2/auth/register/', {
      headers: { Origin: baseURL!, 'X-CSRFToken': csrf_token }, data: owner,
    })
    expect(registration.status()).toBe(201)
    const session = await registration.json() as SessionResponse
    const categoryResponse = await setup.request.get('/api/v2/categories/')
    const categories = await categoryResponse.json() as { results: { id: string }[] }
    const category = categories.results[0]?.id
    expect(category).toBeTruthy()
    reviewCategory = category!
    const common = { category, expires_at: new Date(Date.now() + 14 * 86_400_000).toISOString() }
    await seed(setup, session.access, { ...common,
      question: 'What makes a neighborhood feel like home?',
      description: 'The small things can make a big difference. Which part of your community matters most to you?',
      options: ['Welcoming neighbors', 'Green spaces', 'Local shops', 'Community events'].map(option_text => ({ option_text })),
    })
    await seed(setup, session.access, { ...common,
      question: 'When do your best ideas arrive?',
      description: 'Some of us think best over morning coffee. Others find a little clarity after the day slows down.',
      options: ['Early morning', 'On an afternoon walk', 'Late at night'].map(option_text => ({ option_text })),
    })
    ballot = await seed(setup, session.access, { ...common,
      question: 'What would make your next weekend a good one?',
      description: 'A little space to recharge looks different for everyone. Choose up to two ways you would spend a free afternoon.',
      voting_mode: 'multiple', min_selections: 1, max_selections: 2, results_visibility: 'after_voting',
      options: ['A long walk outdoors', 'A good book and a quiet corner', 'Cooking something new', 'Catching up with friends'].map(option_text => ({ option_text })),
    })
    draft = await seed(setup, session.access, { question: 'Where should our next community gathering happen?',
      description: 'Help us find a welcoming space for our next get-together.',
      options: ['The neighborhood garden', 'The community center'].map(option_text => ({ option_text })),
    }, false)
  } finally { await setup.close() }

  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Put it to a vote.' })).toBeVisible()
  for (const width of [1440, 1024, 768, 390, 320]) {
    await page.setViewportSize({ width, height: width < 600 ? 844 : 1000 })
    await test.step('home at ' + width, () => capture(page, 'home-' + width))
  }
  await page.goto('/polls?category=' + reviewCategory)
  await expect(page.getByRole('link', { name: ballot.question, exact: true })).toBeVisible()
  for (const width of [1440, 1024, 768, 390, 320]) {
    await page.setViewportSize({ width, height: width < 600 ? 844 : 1000 })
    await test.step('discovery at ' + width, () => capture(page, 'discovery-' + width))
  }
  await page.goto('/polls/' + ballot.id)
  await expect(page.getByText(/Results are available only after your account has voted/)).toBeVisible()
  await expect(page.getByRole('table')).toHaveCount(0)
  for (const width of [1440, 1024, 768, 390, 320]) {
    await page.setViewportSize({ width, height: width < 600 ? 844 : 1000 })
    await test.step('guest detail at ' + width, () => capture(page, 'guest-detail-' + width))
  }
  await page.setViewportSize({ width: 1440, height: 1000 })
  for (const [path, name] of [['/login', 'login'], ['/register', 'registration'], ['/not-a-route', 'not-found'], ['/forgot-password', 'recovery']]) {
    await page.goto(path!)
    await capture(page, name!)
  }
  await register(page, credentials('visual_voter'))
  await capture(page, 'my-polls-empty')
  await page.goto('/polls/' + ballot.id)
  await page.getByRole('checkbox', { name: 'A long walk outdoors', exact: true }).check()
  await page.getByRole('checkbox', { name: 'Cooking something new', exact: true }).check()
  await capture(page, 'voting-desktop')
  await page.getByRole('button', { name: 'Submit vote', exact: true }).click()
  await expect(page.getByText('Your vote was saved.', { exact: true })).toBeVisible()
  await expect(page.getByRole('table')).toBeVisible()
  await capture(page, 'results-desktop')
  await page.setViewportSize({ width: 390, height: 844 })
  await capture(page, 'results-mobile')
  await noStoredSecrets(page)

  // A separate browser context keeps creator and voter state/caches isolated.
  const creator = await browser.newContext({ baseURL: baseURL!, viewport: { width: 1440, height: 1000 } })
  try {
    await localOnly(creator, baseURL!)
    const manager = await creator.newPage()
    await login(manager, owner)
    await capture(manager, 'my-polls-desktop')
    for (const [path, name] of [['/polls/new', 'create-desktop'], ['/polls/' + draft.id + '/manage', 'management-desktop'], ['/profile', 'profile-desktop']]) {
      await manager.goto(path!)
      await capture(manager, name!)
    }
    await manager.setViewportSize({ width: 320, height: 844 })
    await capture(manager, 'profile-320')
    await manager.goto('/polls/new')
    await capture(manager, 'create-320')
    await manager.goto('/polls/' + draft.id + '/manage')
    await capture(manager, 'management-320')
    await noStoredSecrets(manager)
  } finally { await creator.close() }
})
