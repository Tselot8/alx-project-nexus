import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { themeFixtures, themePoll, themePollId } from './theme-fixtures'

const axe = readFileSync(createRequire(import.meta.url).resolve('axe-core/axe.min.js'), 'utf8')
async function ready(page: Page) {
  await expect(page.getByRole('main').getByRole('heading', { level: 1 })).toBeVisible()
  await expect(page.locator('.loading')).toHaveCount(0)
  await page.evaluate(() => document.fonts.ready)
}
async function choose(page: Page, theme: 'Light' | 'Dark' | 'Use device setting') {
  if (await page.locator('.theme-control').getAttribute('open') === null) await page.locator('.theme-control > summary').click()
  await page.getByRole('radio', { name: theme, exact: true }).check()
  await page.keyboard.press('Escape')
}
async function audit(page: Page, name: string) {
  await ready(page)
  await page.addScriptTag({ content: axe })
  const failures = await page.evaluate(async () => {
    const report = await (window as unknown as { axe: typeof import('axe-core') }).axe.run(document, {
      runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa', 'best-practice'] },
    })
    return report.violations.map(item => ({ id: item.id, nodes: item.nodes.length }))
  })
  if (failures.length) test.info().annotations.push({ type: 'qa-rules', description: JSON.stringify(failures) })
  expect(failures, name).toEqual([])
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), name + ' reflow').toBe(true)
}

test.describe('guest routes: appearance', () => {
  test('applies a verified dark canvas before React loads, then follows system preference', async ({ page, context, baseURL }) => {
    await themeFixtures(context, baseURL!)
    await page.emulateMedia({ colorScheme: 'dark' })
    let release!: () => void
    const waiting = new Promise<void>(resolve => { release = resolve })
    await page.route(/\/(?:src\/main\.tsx|assets\/index-[^/]+\.js)(?:\?.*)?$/, async route => { await waiting; await route.continue() })
    try {
      await page.goto('/login', { waitUntil: 'commit' })
      await page.waitForFunction(() => document.documentElement.dataset.theme === 'dark')
      expect(await page.evaluate(() => document.documentElement.style.backgroundColor)).toBe('rgb(21, 28, 39)')
      expect(await page.evaluate(() => document.documentElement.style.colorScheme)).toBe('dark')
      expect(await page.evaluate(() => localStorage.length)).toBe(0)
    } finally { release() }
    await ready(page)
    await page.emulateMedia({ colorScheme: 'light' })
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
    await page.emulateMedia({ colorScheme: 'dark' })
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  })

  test('persists explicit choice, preserves a login draft, and returns to system preference', async ({ page, context, baseURL }) => {
    await themeFixtures(context, baseURL!)
    await page.emulateMedia({ colorScheme: 'dark' })
    await page.goto('/login'); await ready(page)
    await page.getByLabel('Email address').fill('visual@example.invalid')
    await choose(page, 'Light')
    await expect(page.getByLabel('Email address')).toHaveValue('visual@example.invalid')
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
    await page.reload(); await ready(page)
    await expect(page.locator('.theme-control > summary')).toHaveAccessibleName('Appearance: light theme')
    await page.getByRole('link', { name: 'Create an account', exact: true }).click()
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
    await choose(page, 'Use device setting')
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
    expect(await page.evaluate(() => localStorage.length)).toBe(0)
  })

  test('synchronizes appearance between tabs without persisting credentials', async ({ page, context, baseURL }) => {
    await themeFixtures(context, baseURL!)
    await page.goto('/login'); await ready(page)
    const other = await context.newPage()
    await other.goto('/register'); await ready(other)
    await choose(page, 'Dark')
    await expect(other.locator('html')).toHaveAttribute('data-theme', 'dark')
    expect(await page.evaluate(() => Object.entries(localStorage))).toEqual([['nexus-theme', 'dark']])
    expect(await page.evaluate(() => sessionStorage.length)).toBe(0)
  })

  test('keeps the appearance selector keyboard accessible and inside the mobile viewport', async ({ page, context, baseURL }) => {
    await themeFixtures(context, baseURL!)
    await page.setViewportSize({ width: 320, height: 844 })
    await page.goto('/login'); await ready(page)
    const summary = page.locator('.theme-control > summary')
    await summary.focus(); await page.keyboard.press('Enter')
    await expect(page.getByRole('group', { name: 'Color theme' })).toBeVisible()
    await page.getByRole('radio', { name: 'Dark', exact: true }).focus()
    await page.keyboard.press(' ')
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
    await audit(page, 'mobile appearance panel')
    await page.keyboard.press('Escape'); await expect(summary).toBeFocused()
    await expect(page.getByRole('group', { name: 'Color theme' })).not.toBeVisible()
    await summary.click(); await page.mouse.click(2, 100)
    await expect(page.getByRole('group', { name: 'Color theme' })).not.toBeVisible()
    await page.evaluate(() => { document.documentElement.style.fontSize = '200%' })
    await summary.click()
    const panel = await page.getByRole('group', { name: 'Color theme' }).boundingBox()
    expect(panel!.x).toBeGreaterThanOrEqual(0)
    expect(panel!.x + panel!.width).toBeLessThanOrEqual(320)
  })

  test('preserves poll configuration and dynamic options while switching themes', async ({ page, context, baseURL }) => {
    await themeFixtures(context, baseURL!, { authenticated: true, owner: true })
    await page.goto('/polls/new'); await ready(page)
    await page.getByLabel('Question', { exact: true }).fill('Which local space should we improve?')
    await page.getByLabel('Voting mode').selectOption('multiple')
    await page.getByLabel('Maximum selections').fill('2')
    await page.getByLabel('Option 1', { exact: true }).fill('The community garden')
    await page.getByRole('button', { name: 'Add option', exact: true }).click()
    await page.getByLabel('Option 3', { exact: true }).fill('The walking trail')
    await choose(page, 'Dark')
    await expect(page.getByLabel('Question', { exact: true })).toHaveValue('Which local space should we improve?')
    await expect(page.getByLabel('Maximum selections')).toHaveValue('2')
    await expect(page.getByLabel('Option 3', { exact: true })).toHaveValue('The walking trail')
    await page.getByRole('button', { name: 'Review & publish' }).click()
    await expect(page.getByRole('alert').first()).toBeVisible()
    await audit(page, 'dark publication validation')
  })

  test('preserves complete ballot selections, submission and results while changing appearance', async ({ page, context, baseURL }) => {
    await themeFixtures(context, baseURL!, { authenticated: true })
    await page.goto('/polls/' + themePollId); await ready(page)
    await page.getByRole('checkbox', { name: themePoll.options[0]!.option_text, exact: true }).check()
    await choose(page, 'Dark')
    await expect(page.getByRole('checkbox', { name: themePoll.options[0]!.option_text, exact: true })).toBeChecked()
    await page.getByRole('checkbox', { name: themePoll.options[1]!.option_text, exact: true }).check()
    await expect(page.getByRole('checkbox', { name: themePoll.options[2]!.option_text, exact: true })).toBeDisabled()
    await audit(page, 'dark selected, unselected and disabled ballot options')
    await page.getByRole('button', { name: 'Submit vote', exact: true }).click()
    await expect(page.getByText('Your vote was saved.', { exact: true })).toBeVisible()
    await choose(page, 'Light')
    await expect(page.getByRole('checkbox', { name: /A long walk outdoors/ })).toBeChecked()
    await expect(page.getByRole('button', { name: 'Update vote', exact: true })).toBeDisabled()
    await expect(page.getByRole('table')).toBeVisible()
  })

  test('dark single-choice controls keep keyboard selection and replacement intact', async ({ page, context, baseURL }) => {
    await themeFixtures(context, baseURL!, { authenticated: true, single: true, submitted: true })
    await page.emulateMedia({ colorScheme: 'dark' })
    await page.goto('/polls/' + themePollId); await ready(page)
    const selected = page.getByRole('radio', { name: /A long walk outdoors/ })
    await selected.focus(); await page.keyboard.press('ArrowDown')
    await expect(page.getByRole('radio', { name: themePoll.options[1]!.option_text, exact: true })).toBeChecked()
    await choose(page, 'Light')
    await expect(page.getByRole('radio', { name: themePoll.options[1]!.option_text, exact: true })).toBeChecked()
    await page.getByRole('button', { name: 'Update vote', exact: true }).click()
    await expect(page.getByText('Your ballot was updated. The complete selection set has replaced your previous choices.', { exact: true })).toBeVisible()
  })

  test('keeps the appearance control separate from navigation at all widths and enlarged text', async ({ page, context, baseURL }) => {
    await themeFixtures(context, baseURL!)
    await page.goto('/login'); await ready(page)
    for (const scale of ['100%', '200%']) {
      await page.evaluate(value => { document.documentElement.style.fontSize = value }, scale)
      for (const width of [320, 390, 768, 1024, 1440]) {
        await page.setViewportSize({ width, height: 1000 })
        await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
        const overlaps = await page.evaluate(() => {
          const control = document.querySelector('.theme-control > summary')!.getBoundingClientRect()
          return Array.from(document.querySelectorAll('.header-inner a, .header-inner button')).filter(element => {
            const box = element.getBoundingClientRect()
            return box.width && box.height && box.left < control.right && box.right > control.left && box.top < control.bottom && box.bottom > control.top
          }).length
        })
        await test.step('Header at ' + width + ' / ' + scale, async () => { expect(overlaps).toBe(0) })
      }
    }
  })

  test('dark pages pass rendered contrast, accessibility and responsive checks', async ({ browser, baseURL }) => {
    test.setTimeout(180_000)
    const cases: [string, Parameters<typeof themeFixtures>[2]][] = [
      ['/', {}], ['/polls', {}], ['/login', {}], ['/register', {}],
      ['/polls/' + themePollId, { authenticated: true, submitted: true }],
      ['/my-polls', { authenticated: true, owner: true }], ['/polls/new', { authenticated: true, owner: true }],
      ['/polls/' + themePollId + '/manage', { authenticated: true, owner: true }], ['/profile', { authenticated: true }],
      ['/polls/' + themePollId, { authenticated: true, status: 'closed' }],
      ['/polls', { empty: true }], ['/polls', { error: true }], ['/not-a-route', {}], ['/forgot-password', {}],
    ]
    for (const [path, fixture] of cases) {
      const context = await browser.newContext({ baseURL: baseURL!, colorScheme: 'dark', reducedMotion: 'reduce' })
      try {
        await themeFixtures(context, baseURL!, fixture)
        const page = await context.newPage()
        await page.goto(path); await ready(page)
        for (const width of [320, 390, 768, 1024, 1440]) {
          await page.setViewportSize({ width, height: width < 600 ? 844 : 1000 })
          await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
          await test.step('Dark reflow ' + path + ' at ' + width, async () => {
            expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
          })
        }
        await audit(page, 'dark ' + path)
        await page.setViewportSize({ width: 390, height: 844 })
        await audit(page, 'dark mobile ' + path)
      } finally { await context.close() }
    }
  })
})
