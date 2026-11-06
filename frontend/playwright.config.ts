import { defineConfig } from '@playwright/test'
import { existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { basename, dirname, join, resolve } from 'node:path'

const baseURL = process.env.NEXUS_E2E_BASE_URL
const artifacts = process.env.NEXUS_E2E_ARTIFACTS || ''
if (baseURL !== 'http://127.0.0.1:5181' || !/^[a-f0-9]{12}$/.test(process.env.NEXUS_INTEGRATION_RUN || '')
  || dirname(resolve(artifacts)).toLowerCase() !== resolve(tmpdir()).toLowerCase()
  || !basename(artifacts).startsWith('nexus-i-browser-') || !existsSync(artifacts)) {
  throw new Error('Use the owned disposable stack: python scripts/verify_fullstack.py')
}
export default defineConfig({
  testDir: './e2e', testMatch: '**/*.pw.ts', workers: 1, fullyParallel: false,
  forbidOnly: true, retries: 0, timeout: 60_000,
  expect: { timeout: 10_000 },
  outputDir: join(resolve(artifacts), 'artifacts'),
  reporter: [['./e2e/reporter.ts']],
  use: {
    baseURL, headless: true, channel: 'chrome', viewport: { width: 1280, height: 900 },
    serviceWorkers: 'block', trace: 'off', screenshot: 'off', video: 'off',
    launchOptions: { args: ['--disable-background-networking', '--disable-component-update', '--no-proxy-server'] },
  },
  projects: [
    { name: 'desktop-chrome', testMatch: '**/journeys.pw.ts' },
    { name: 'qa-desktop', testMatch: '**/qa.pw.ts' },
    { name: 'qa-tablet', testMatch: '**/qa.pw.ts', use: { viewport: { width: 768, height: 1024 }, hasTouch: true } },
    { name: 'qa-mobile', testMatch: '**/qa.pw.ts', use: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } },
    { name: 'mobile-chrome', testMatch: '**/mobile.pw.ts',
      use: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } },
  ],
})
