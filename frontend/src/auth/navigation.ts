/** Never retain fragments, credentials or arbitrary external redirect targets. */
export function safeReturnTo(value: string | null, fallback = '/my-polls'): string {
  if (!value || !value.startsWith('/') || value.startsWith('//') || /\\|%5c|%2f/i.test(value)) return fallback
  const url = new URL(value, window.location.origin)
  if (url.origin !== window.location.origin || url.hash) return fallback
  if (!/^\/(my-polls|profile|polls(?:\/[^/]+(?:\/manage)?)?)\/?$/.test(url.pathname)) return fallback
  // No redirect query strings: private credentials cannot hitchhike into history.
  return url.pathname
}

/** Recovery is disabled: discard old reset-link credentials before bootstrap. */
export function discardRecoveryCredentials(browser: Pick<Window, 'location' | 'history'>) {
  if (browser.location.pathname === '/reset-password' && (browser.location.hash || browser.location.search)) {
    browser.history.replaceState(browser.history.state, '', '/reset-password')
  }
}
