import { expect, test } from '@playwright/test'
import { localOnly, noStoredSecrets, register } from './helpers'

test('mobile menu, session restoration, protected navigation and logout work at 390px', async ({ page, context, baseURL }) => {
  await localOnly(context, baseURL!)
  await test.step('register and navigate with the mobile menu', async () => {
    await register(page)
    await page.getByRole('button', { name: 'Menu', exact: true }).click()
    await expect(page.getByRole('navigation', { name: 'Mobile' })).toBeVisible()
    await page.getByRole('navigation', { name: 'Mobile' }).getByRole('link', { name: 'My profile' }).click()
    await expect(page).toHaveURL(/\/profile$/)
    await expect(page.getByRole('navigation', { name: 'Mobile' })).toBeHidden()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.reload()
    await expect(page.getByRole('heading', { name: 'A little more you.' })).toBeVisible()
    await noStoredSecrets(page)
  })
  await test.step('sign out without reviving a protected mobile page', async () => {
    await page.getByRole('button', { name: 'Menu', exact: true }).click()
    await page.getByRole('navigation', { name: 'Mobile' }).getByRole('button', { name: 'Sign out', exact: true }).click()
    await expect(page).toHaveURL(/\/login\?returnTo=/)
    await page.reload()
    await expect(page.getByLabel('Email address')).toBeVisible()
  })
})
