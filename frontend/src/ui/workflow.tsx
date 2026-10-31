import { useEffect, useRef, useState } from 'react'
import type { ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from 'react'
import { ApiError } from '../api/http'
import { Button, Feedback } from './components'

export function useAction() {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const [message, setMessage] = useState('')
  const flight = useRef(false)
  const mounted = useRef(true)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  async function run(action: () => Promise<void>, success = '') {
    if (flight.current) return false
    flight.current = true
    setBusy(true); setError(null); setMessage('')
    try {
      await action()
      if (mounted.current) setMessage(success)
      return true
    } catch (failure) {
      if (mounted.current && !(failure instanceof DOMException && failure.name === 'AbortError')) {
        setError(failure instanceof ApiError ? failure : new ApiError(0, 'request_failed', 'The action could not be confirmed. Reload before trying again.'))
      }
      return false
    } finally { flight.current = false; if (mounted.current) setBusy(false) }
  }
  return { busy, error, message, run, clear: () => { setError(null); setMessage('') } }
}
export type Action = ReturnType<typeof useAction>
export function ActionFeedback({ action }: { action: Action }) {
  const summary = useRef<HTMLDivElement>(null)
  useEffect(() => { if (action.error) summary.current?.focus() }, [action.error])
  return <><div ref={summary} tabIndex={-1}>
    {action.error && <Feedback tone="error">{action.error.status === 409
      ? 'This action conflicts with the current poll state. Reload and review before trying again.'
      : action.error.status === 403 ? 'You no longer have permission to make this change.'
      : action.error.status === 404 ? 'This resource is no longer available.' : action.error.message}
      {!!Object.keys(action.error.fieldErrors).length && <ul>{Object.entries(action.error.fieldErrors).map(([key, values]) =>
        <li key={key}>{key.replaceAll('_', ' ')}: {values.join(' ')}</li>)}</ul>}
    </Feedback>}
  </div>{action.message && <Feedback tone="success">{action.message}</Feedback>}</>
}
export function SelectField({ label, error, children, ...props }: SelectHTMLAttributes<HTMLSelectElement> & { label: string; error?: readonly string[] | undefined }) {
  return <div className="field"><label htmlFor={props.id}>{label}</label>
    <select {...props} aria-invalid={!!error?.length || undefined} aria-describedby={error?.length ? props.id + '-error' : undefined}>{children}</select>
    {!!error?.length && <span className="field-error" id={props.id + '-error'}>{error.join(' ')}</span>}</div>
}
export function TextareaField({ label, error, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement> & { label: string; error?: readonly string[] | undefined }) {
  return <div className="field"><label htmlFor={props.id}>{label}</label>
    <textarea {...props} aria-invalid={!!error?.length || undefined} aria-describedby={error?.length ? props.id + '-error' : undefined} />
    {!!error?.length && <span className="field-error" id={props.id + '-error'}>{error.join(' ')}</span>}</div>
}
/** Deliberate inline confirmation avoids modal focus traps and supports narrow screens. */
export function Confirmation({ title, children, confirm, cancel, busy, label = 'Confirm' }: {
  title: string; children: ReactNode; confirm: () => void; cancel: () => void; busy: boolean; label?: string
}) {
  const heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null
    heading.current?.focus()
    return () => { if (trigger?.isConnected) trigger.focus() }
  }, [])
  return <section className="confirmation" aria-label={title}>
    <h3 tabIndex={-1} ref={heading}>{title}</h3><div>{children}</div>
    <div className="action-row"><Button pending={busy} onClick={confirm}>{label}</Button>
      <Button disabled={busy} variant="secondary" onClick={cancel}>Cancel</Button></div>
  </section>
}
/** Explicit saves only. Guard refresh/close and in-app link navigation without storing form data. */
export function useUnsavedChanges(dirty: boolean) {
  useEffect(() => {
    if (!dirty) return
    const unload = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    const link = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
      const target = event.target instanceof Element ? event.target.closest('a[href]') : null
      if (!(target instanceof HTMLAnchorElement) || target.hash === '#main-content' || target.target === '_blank') return
      if (!window.confirm('Leave without saving your changes?')) { event.preventDefault(); event.stopPropagation() }
    }
    window.addEventListener('beforeunload', unload)
    document.addEventListener('click', link, true)
    return () => { window.removeEventListener('beforeunload', unload); document.removeEventListener('click', link, true) }
  }, [dirty])
}
