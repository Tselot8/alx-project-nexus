import { useId } from 'react'
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from 'react'

export function Button({ variant = 'primary', pending = false, children, disabled, ...props }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'quiet'; pending?: boolean }) {
  return <button {...props} className={'button button--' + variant} disabled={disabled || pending}
    aria-busy={pending || undefined}>{pending && <span className="spinner" aria-hidden="true" />}{children}</button>
}
export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <section className={'card ' + className}>{children}</section>
}
export function Field({ label, error, hint, ...props }:
  InputHTMLAttributes<HTMLInputElement> & { label: string; error?: readonly string[] | undefined; hint?: string | undefined }) {
  const autoId = useId()
  const id = props.id || autoId
  const description = [hint && id + '-hint', error?.length && id + '-error'].filter(Boolean).join(' ') || undefined
  return <div className="field">
    <label htmlFor={id}>{label}</label>
    <input {...props} id={id} aria-describedby={description} aria-invalid={!!error?.length || undefined} />
    {hint && <span id={id + '-hint'} className="field-hint">{hint}</span>}
    {!!error?.length && <span id={id + '-error'} className="field-error">{error.join(' ')}</span>}
  </div>
}
export function Feedback({ children, tone = 'info' }: { children: ReactNode; tone?: 'info' | 'error' | 'success' }) {
  return <div className={'feedback feedback--' + tone} role={tone === 'error' ? 'alert' : 'status'}>{children}</div>
}
export function Loading({ label = 'Loading…' }: { label?: string }) {
  return <div className="loading" role="status"><span className="spinner" aria-hidden="true" />{label}</div>
}
export function EmptyState({ title, children }: { title: string; children: ReactNode }) {
  return <div className="empty-state"><span className="empty-symbol" aria-hidden="true">↗</span>
    <h2>{title}</h2><p>{children}</p></div>
}
export function Initials({ name }: { name: string }) {
  const text = name.trim().split(/[\s_-]+/).slice(0, 2).map(part => part[0]).join('').toUpperCase() || 'N'
  return <span className="avatar" aria-hidden="true">{text}</span>
}
