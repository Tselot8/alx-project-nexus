import { useEffect, useLayoutEffect, useRef, useSyncExternalStore } from 'react'

type Preference = 'system' | 'light' | 'dark'
declare global {
  interface Window {
    nexusTheme?: {
      getSnapshot: () => string
      subscribe: (listener: () => void) => () => void
      setPreference: (preference: Preference) => void
    }
  }
}
const subscribe = (listener: () => void) => window.nexusTheme?.subscribe(listener) || (() => {})
const snapshot = () => window.nexusTheme?.getSnapshot() || 'system:light'

export function useTheme() { return useSyncExternalStore(subscribe, snapshot, () => 'system:light') }

export function ThemeControl() {
  const [preference, theme] = useTheme().split(':')
  const details = useRef<HTMLDetailsElement>(null)
  const summary = useRef<HTMLElement>(null)
  useLayoutEffect(() => {
    const control = details.current
    const header = control?.closest('.header-inner')
    if (!control || !header) return
    const anchors = Array.from(header.querySelectorAll<HTMLElement>('.desktop-actions, .mobile-menu-toggle'))
    const place = () => {
      const anchor = anchors.find(item => item.getBoundingClientRect().width > 0)
      if (!anchor) return
      const box = anchor.getBoundingClientRect(), parent = header.getBoundingClientRect()
      // Follow the real navigation row when enlarged text wraps the header.
      // This control never changes the layout or spacing of existing items.
      control.style.setProperty('--theme-left', Math.max(0, box.left - parent.left - 56) + 'px')
      control.style.setProperty('--theme-top', box.top - parent.top + (box.height - 44) / 2 + 'px')
      const left = parent.left + Math.min(Math.max(0, box.left - parent.left - 56), Math.max(0, parent.width - 44))
      const panelLeft = Math.max(16, Math.min(left + 44 - 224, window.innerWidth - 240))
      control.style.setProperty('--theme-panel-left', panelLeft - left + 'px')
    }
    place()
    const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(place) : null
    observer?.observe(header)
    for (const anchor of anchors) observer?.observe(anchor)
    window.addEventListener('resize', place)
    return () => { observer?.disconnect(); window.removeEventListener('resize', place) }
  }, [])
  useEffect(() => {
    const outside = (event: PointerEvent) => {
      if (event.target instanceof Node && details.current && !details.current.contains(event.target)) details.current.open = false
    }
    document.addEventListener('pointerdown', outside)
    return () => document.removeEventListener('pointerdown', outside)
  }, [])
  return <details className="theme-control" ref={details} onKeyDown={event => {
    if (event.key === 'Escape' && details.current?.open) {
      event.stopPropagation(); details.current.open = false; summary.current?.focus()
    }
  }}>
    <summary ref={summary} aria-label={'Appearance: ' + theme + ' theme'} title="Change color theme">
      <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" focusable="false">
        {theme === 'dark' ? <path d="M20 15.2A8.8 8.8 0 0 1 8.8 4 8.8 8.8 0 1 0 20 15.2Z" /> : <>
          <circle cx="12" cy="12" r="4" /><path d="M12 2v2m0 16v2M2 12h2m16 0h2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
        </>}
      </svg>
    </summary>
    <fieldset className="theme-panel"><legend>Color theme</legend>
      {(['light', 'dark', 'system'] as const).map(value => <label key={value}>
        <input type="radio" name="nexus-appearance" value={value} checked={preference === value} onChange={() => window.nexusTheme?.setPreference(value)} />
        <span>{value === 'system' ? 'Use device setting' : value === 'light' ? 'Light' : 'Dark'}</span>
      </label>)}
      <p role="status">{theme === 'dark' ? 'Dark theme active' : 'Light theme active'}</p>
    </fieldset>
  </details>
}
