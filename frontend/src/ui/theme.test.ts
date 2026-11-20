import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { runInNewContext } from 'node:vm'
import { describe, expect, it, vi } from 'vitest'

const source = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '../../public/assets/theme-init.js'), 'utf8')
function boot(saved: string | null = null, dark = false, blocked = false, legacy = false) {
  let value = saved
  const callbacks: Record<string, (event: { key?: string | null }) => void> = {}
  let mediaChange = () => {}
  const media = { matches: dark, addEventListener: legacy ? undefined : vi.fn((_name: string, fn: () => void) => { mediaChange = fn }), addListener: vi.fn((fn: () => void) => { mediaChange = fn }) }
  const element = { dataset: {} as Record<string, string>, style: {} as Record<string, string> }
  const meta = { setAttribute: vi.fn() }
  const storage = {
    getItem: vi.fn(() => { if (blocked) throw new Error('unavailable'); return value }),
    setItem: vi.fn((_key: string, next: string) => { if (blocked) throw new Error('unavailable'); value = next }),
    removeItem: vi.fn(() => { if (blocked) throw new Error('unavailable'); value = null }),
  }
  type Controller = { getSnapshot: () => string; setPreference: (value: string) => void; subscribe: (fn: () => void) => () => void }
  const window = { nexusTheme: undefined as Controller | undefined, localStorage: storage, matchMedia: () => media,
    addEventListener: vi.fn((name: string, fn: typeof callbacks[string]) => { callbacks[name] = fn }) }
  const document = { documentElement: element, querySelector: () => meta }
  const execute = () => runInNewContext(source, { window, document })
  execute()
  return { controller: window.nexusTheme!, storage, element, meta, window, execute,
    system: (next: boolean) => { media.matches = next; mediaChange() },
    external: (next: string | null, key: string | null = 'nexus-theme') => { value = next; callbacks.storage?.({ key }) } }
}

describe('pre-paint appearance bootstrap', () => {
  it.each([false, true])('follows device preference without writing storage (%s)', dark => {
    const state = boot(null, dark)
    expect(state.controller.getSnapshot()).toBe('system:' + (dark ? 'dark' : 'light'))
    expect(state.element.dataset.theme).toBe(dark ? 'dark' : 'light')
    expect(state.element.style.colorScheme).toBe(dark ? 'dark' : 'light')
    expect(state.element.style.backgroundColor).toBe(dark ? '#151C27' : '#FAF8F3')
    expect(state.storage.setItem).not.toHaveBeenCalled()
  })
  it.each(['light', 'dark'])('honors an explicit %s preference over the system', preference => {
    const state = boot(preference, preference !== 'dark')
    expect(state.controller.getSnapshot()).toBe(preference + ':' + preference)
  })
  it('ignores malformed saved values and invalid new choices', () => {
    const state = boot('unexpected', true)
    state.controller.setPreference('unsupported')
    expect(state.controller.getSnapshot()).toBe('system:dark')
    expect(state.storage.setItem).not.toHaveBeenCalled()
  })
  it('responds to system changes only while following the system', () => {
    const state = boot()
    state.system(true)
    expect(state.controller.getSnapshot()).toBe('system:dark')
    state.controller.setPreference('light')
    state.system(false); state.system(true)
    expect(state.controller.getSnapshot()).toBe('light:light')
    expect(state.storage.setItem).toHaveBeenLastCalledWith('nexus-theme', 'light')
  })
  it('can return to device preference without leaving a stored override', () => {
    const state = boot('light', true)
    state.controller.setPreference('system')
    expect(state.storage.removeItem).toHaveBeenCalledWith('nexus-theme')
    expect(state.controller.getSnapshot()).toBe('system:dark')
  })
  it('still switches appearance when browser storage is blocked', () => {
    const state = boot(null, true, true)
    expect(state.controller.getSnapshot()).toBe('system:dark')
    expect(() => state.controller.setPreference('light')).not.toThrow()
    expect(state.controller.getSnapshot()).toBe('light:light')
  })
  it('synchronizes relevant cross-tab storage changes and clears', () => {
    const state = boot('light', true)
    state.external('dark')
    expect(state.controller.getSnapshot()).toBe('dark:dark')
    state.external(null, null)
    expect(state.controller.getSnapshot()).toBe('system:dark')
  })
  it('does not react to unrelated storage events', () => {
    const state = boot('light')
    state.external('dark', 'unrelated')
    expect(state.controller.getSnapshot()).toBe('light:light')
  })
  it('notifies subscribers once per change and honors unsubscription', () => {
    const state = boot()
    const listener = vi.fn()
    const stop = state.controller.subscribe(listener)
    state.controller.setPreference('dark'); state.controller.setPreference('dark')
    expect(listener).toHaveBeenCalledTimes(1)
    stop(); state.controller.setPreference('light')
    expect(listener).toHaveBeenCalledTimes(1)
  })
  it('updates the browser theme color without sensitive values', () => {
    const state = boot()
    state.controller.setPreference('dark')
    expect(state.meta.setAttribute).toHaveBeenLastCalledWith('content', '#151C27')
  })
  it('initializes only once, even when called twice', () => {
    const state = boot()
    const controller = state.controller
    state.execute()
    expect(state.window.nexusTheme).toBe(controller)
    expect(state.window.addEventListener).toHaveBeenCalledTimes(1)
  })
  it('supports the older media-query listener API', () => {
    const state = boot(null, false, false, true)
    state.system(true)
    expect(state.controller.getSnapshot()).toBe('system:dark')
  })
})
