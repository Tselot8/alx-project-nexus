import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import type { Category, PollSummary } from '../../api/contracts'

export function useNow(deadline?: string | null) {
  const [now, setNow] = useState(Date.now)
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 15_000)
    const remaining = deadline ? Date.parse(deadline) - Date.now() : NaN
    const expiry = Number.isFinite(remaining) && remaining < 2_147_483_647
      ? window.setTimeout(() => setNow(Date.now()), Math.max(0, remaining) + 1) : undefined
    return () => { window.clearInterval(timer); window.clearTimeout(expiry) }
  }, [deadline])
  return now
}
export function pollState(poll: PollSummary, now = Date.now()) {
  if (poll.status === 'archived') return 'Archived'
  if (poll.status === 'draft') return 'Draft'
  if (poll.expires_at && Date.parse(poll.expires_at) <= now) return poll.status === 'published' ? 'Expired' : 'Closed · deadline passed'
  return poll.status === 'closed' ? 'Closed' : 'Open'
}
export function DateLabel({ value }: { value: string }) {
  const valid = !Number.isNaN(Date.parse(value))
  return valid ? <time dateTime={value}>{new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))}</time> : <>Date unavailable</>
}
export function CategoryLabel({ id, categories }: { id: string | null; categories: Category[] }) {
  const category = categories.find(item => item.id === id)
  return <>{category?.name || (id ? 'Category not loaded' : 'Uncategorized')}</>
}
export function PollCard({ poll, categories, now }: { poll: PollSummary; categories: Category[]; now: number }) {
  return <article className="card poll-card">
    <div className="poll-badges"><span className="pill">{pollState(poll, now)}</span>
      <span className="metadata"><CategoryLabel id={poll.category} categories={categories} /></span></div>
    <h2><Link to={'/polls/' + poll.id}>{poll.question || 'Untitled draft'}</Link></h2>
    {poll.description && <p className="description-preview">{poll.description}</p>}
    <div className="poll-card-footer"><span>{poll.voting_mode === 'single' ? 'Single choice' : 'Multiple choice'}</span>
      <span>Public poll</span></div>
    <p className="metadata">{poll.expires_at ? <>Closing date: <DateLabel value={poll.expires_at} /></> : 'No scheduled closing date'}</p>
  </article>
}
