import { useState } from 'react'
import { Link, useLocation, useSearchParams } from 'react-router'
import { useServices, useSession } from '../app/providers'
import type { PollStatus } from '../api/contracts'
import { ApiError } from '../api/http'
import { useMyPolls } from '../features/creator/api'
import type { MineFilters } from '../features/creator/api'
import { CategorySelect } from '../features/creator/poll-editor'
import { uuidPattern, useCategories } from '../features/polls/api'
import { CategoryLabel, DateLabel, pollState, useNow } from '../features/polls/presentation'
import { Button, Card, EmptyState, Feedback, Field, Loading } from '../ui/components'
import { SelectField } from '../ui/workflow'

export function MyPolls() {
  const services = useServices()
  const snapshot = useSession()
  if (snapshot.status !== 'authenticated') return null
  return <Mine key={snapshot.user.id + ':' + services.session.generation} user={snapshot.user.id} />
}
function Mine({ user }: { user: string }) {
  const services = useServices()
  const [params, setParams] = useSearchParams()
  const location = useLocation()
  const page = Number(params.get('page') || 1)
  const status = params.get('status') || ''
  const sort = params.get('sort')
  const category = params.get('category') || ''
  const filters: MineFilters = {
    q: (params.get('q') || '').slice(0, 200), status: ['draft', 'published', 'closed', 'archived'].includes(status) ? status as PollStatus : '',
    sort: sort === 'oldest' || sort === 'closing_soon' ? sort : 'newest',
    category: uuidPattern.test(category) ? category : '', page: Number.isSafeInteger(page) && page > 0 ? page : 1,
  }
  const query = useMyPolls(services, user, filters)
  const categories = useCategories(services.api, 1)
  const now = useNow()
  function update(values: Record<string, string>) {
    const next = new URLSearchParams(params)
    next.set('page', '1')
    for (const [key, value] of Object.entries(values)) { if (value) next.set(key, value); else next.delete(key) }
    // Forward only known inputs to the API even if the browser URL contains extras.
    setParams(next)
  }
  return <section className="discovery-section"><div className="page-heading"><p className="eyebrow">Your workspace</p>
    <h1>Good questions start with you.</h1><p className="page-lead">Your drafts, open questions, and completed polls. Only your own polls appear here.</p>
    <Link className="button button--primary" to="/polls/new">Create a poll</Link></div>
    {typeof location.state?.notice === 'string' && <Feedback tone="success">{location.state.notice}</Feedback>}
    <Card><MineSearch key={location.key} value={filters.q} submit={q => update({ q })} />
      <div className="filter-grid"><SelectField label="Poll status" id="mine-status" value={filters.status} onChange={event => update({ status: event.target.value })}>
        <option value="">All statuses</option><option value="draft">Draft</option><option value="published">Open</option><option value="closed">Closed</option><option value="archived">Archived</option></SelectField>
        <SelectField label="Sort your polls" id="mine-sort" value={filters.sort} onChange={event => update({ sort: event.target.value })}>
          <option value="newest">Newest first</option><option value="oldest">Oldest first</option><option value="closing_soon">Closing soon</option></SelectField>
        <CategorySelect value={filters.category} disabled={false} change={value => update({ category: value })} />
      </div></Card>
    <div className="results-topline"><h2>My polls</h2><Link to="/my-polls">Clear filters</Link></div>
    {query.isPending ? <Loading label="Loading your polls…" /> : query.isError ? <Card><Feedback tone="error">{query.error instanceof ApiError && query.error.status === 404
      ? 'This page is no longer available. Return to the first page.' : 'We could not load your polls.'}</Feedback>
      <Button onClick={() => { if (filters.page > 1) update({ page: '1' }); else void query.refetch() }}>Retry My polls</Button></Card>
      : <><p role="status">{query.data.count} {query.data.count === 1 ? 'poll' : 'polls'} found</p>
        {query.data.results.length ? <div className="poll-grid">{query.data.results.map(poll => <article className="card poll-card" key={poll.id}>
          <div className="poll-badges"><span className="pill">{pollState(poll, now)}</span><span className="pill pill--neutral">{poll.visibility === 'private' ? 'Private' : 'Public'}</span></div>
          <h2><Link to={'/polls/' + poll.id + '/manage'}>{poll.question || 'Untitled draft'}</Link></h2>
          <p><CategoryLabel id={poll.category} categories={categories.data?.results || []} /></p>
          <p className="metadata">{poll.expires_at ? <>Closes <DateLabel value={poll.expires_at} /></> : 'No scheduled closing date'}</p>
          <div className="action-row"><Link className="button button--secondary" to={'/polls/' + poll.id + '/manage'}>Manage poll</Link><Link to={'/polls/' + poll.id}>View poll</Link></div>
        </article>)}</div> : <Card><EmptyState title="No polls here yet.">Create your first question, or adjust the filters to find your polls.</EmptyState></Card>}
        {!!query.data.results.length && <nav className="pagination" aria-label="My polls pages">
          <Button variant="secondary" disabled={!query.data.previous || filters.page <= 1} onClick={() => update({ page: String(filters.page - 1) })}>Previous page</Button>
          <span aria-current="page">Page {filters.page}</span><Button variant="secondary" disabled={!query.data.next} onClick={() => update({ page: String(filters.page + 1) })}>Next page</Button>
        </nav>}
      </>}
  </section>
}
function MineSearch({ value, submit }: { value: string; submit: (value: string) => void }) {
  const [draft, setDraft] = useState(value)
  return <form className="poll-search" role="search" onSubmit={event => { event.preventDefault(); submit(draft.trim()) }}>
    <Field label="Search your polls" type="search" maxLength={200} value={draft} onChange={event => setDraft(event.target.value)} /><Button type="submit">Search</Button>
  </form>
}
