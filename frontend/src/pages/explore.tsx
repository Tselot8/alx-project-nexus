import { useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useLocation, useSearchParams } from 'react-router'
import { useServices } from '../app/providers'
import type { DiscoveryFilters } from '../features/polls/api'
import { useCategories, usePublicPolls, uuidPattern } from '../features/polls/api'
import { PollCard, useNow } from '../features/polls/presentation'
import { ApiError } from '../api/http'
import { Button, Card, EmptyState, Feedback, Field, Loading } from '../ui/components'

export function filtersFromUrl(params: URLSearchParams): DiscoveryFilters {
  const page = Number(params.get('page') || 1)
  const sort = params.get('sort')
  const status = params.get('status')
  const category = params.get('category')
  return {
    ...(params.get('q')?.trim() ? { q: params.get('q')!.trim().slice(0, 200) } : {}),
    ...(category && uuidPattern.test(category) ? { category } : {}),
    page: Number.isSafeInteger(page) && page >= 1 ? page : 1,
    sort: sort === 'oldest' || sort === 'closing_soon' ? sort : 'newest',
    ...(status === 'published' || status === 'closed' ? { status } : {}),
  }
}
function SearchForm({ value, search }: { value: string; search: (q: string) => void }) {
  const [draft, setDraft] = useState(value)
  function submit(event: FormEvent) { event.preventDefault(); search(draft.trim()) }
  return <form role="search" className="poll-search" onSubmit={submit}>
    <Field label="Search polls" type="search" name="q" maxLength={200} value={draft}
      placeholder="A question, a topic, a new perspective…" onChange={event => setDraft(event.target.value)} />
    <Button type="submit">Search</Button>
  </form>
}
export function Explore() {
  const { api } = useServices()
  const [params, setParams] = useSearchParams()
  const location = useLocation()
  const filters = filtersFromUrl(params)
  const [categoryPage, setCategoryPage] = useState(1)
  const categories = useCategories(api, categoryPage)
  const polls = usePublicPolls(api, filters)
  const now = useNow()
  const heading = useRef<HTMLHeadingElement>(null)
  const update = (changes: Record<string, string>, pagination = false) => {
    const next = new URLSearchParams()
    if (filters.q) next.set('q', filters.q)
    if (filters.category) next.set('category', filters.category)
    if (filters.status) next.set('status', filters.status)
    next.set('sort', filters.sort || 'newest')
    next.set('page', '1')
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value); else next.delete(key)
    }
    setParams(next)
    if (pagination) heading.current?.focus()
  }
  const page = filters.page || 1
  const pageMissing = polls.error instanceof ApiError && polls.error.status === 404
  return <section className="discovery-section">
    <div className="page-heading"><p className="eyebrow">Explore polls</p>
      <h1>A good question is a great beginning.</h1>
      <p className="page-lead">Discover public questions. Find a topic that matters to you.</p></div>
    <Card className="discovery-controls">
      <SearchForm key={location.key} value={filters.q || ''} search={q => update({ q }, true)} />
      <div className="filter-grid">
        <div className="field"><label htmlFor="category">Category</label>
          <select id="category" value={filters.category || ''} onChange={event => update({ category: event.target.value })}>
            <option value="">All categories</option>
            {filters.category && !categories.data?.results.some(item => item.id === filters.category)
              && <option value={filters.category}>Selected category (not on this list page)</option>}
            {categories.data?.results.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
        </div>
        <div className="field"><label htmlFor="poll-status">Status</label>
          <select id="poll-status" value={filters.status || ''} onChange={event => update({ status: event.target.value })}>
            <option value="">Open and closed</option><option value="published">Open</option><option value="closed">Closed</option>
          </select></div>
        <div className="field"><label htmlFor="sort">Sort by</label>
          <select id="sort" value={filters.sort} onChange={event => update({ sort: event.target.value })}>
            <option value="newest">Newest first</option><option value="oldest">Oldest first</option><option value="closing_soon">Closing soon</option>
          </select></div>
      </div>
      {categories.isPending && <Loading label="Loading categories…" />}
      {categories.isError && <Feedback tone="error">Categories could not be loaded. Search is still available.
        <Button variant="secondary" onClick={() => { void categories.refetch() }}>Retry categories</Button></Feedback>}
      {categories.data && (categories.data.next || categoryPage > 1) && <nav className="category-paging" aria-label="Category choices">
        <Button variant="quiet" disabled={categoryPage === 1} onClick={() => setCategoryPage(categoryPage - 1)}>Previous categories</Button>
        <span>Category page {categoryPage}</span>
        <Button variant="quiet" disabled={!categories.data.next} onClick={() => setCategoryPage(categoryPage + 1)}>More categories</Button>
      </nav>}
    </Card>
    <div className="results-topline"><h2 ref={heading} tabIndex={-1}>Public polls</h2>
      <Link to="/polls" onClick={() => setCategoryPage(1)}>Clear filters</Link></div>
    <p role="status" aria-live="polite" aria-atomic="true" className="metadata">
      {polls.isPending ? 'Finding polls…' : polls.isError ? 'Polls could not be loaded.'
        : polls.data.count + (polls.data.count === 1 ? ' public poll found' : ' public polls found')}
    </p>
    {polls.isPending ? <Loading label="Loading public polls…" /> : polls.isError ? <Card>
      <Feedback tone="error">{pageMissing ? 'This results page is no longer available. Try the first page.' : 'We could not load polls. Please try again.'}</Feedback>
      {pageMissing ? <Button onClick={() => update({ page: '1' })}>Go to first page</Button>
        : <Button onClick={() => { void polls.refetch() }}>Retry polls</Button>}
    </Card> : polls.data.results.length === 0 ? <Card>
      <EmptyState title="No polls found">Try another search or clear your filters to explore more questions.</EmptyState>
    </Card> : <>
      <div className="poll-grid">{polls.data.results.map(poll => <PollCard key={poll.id} poll={poll} categories={categories.data?.results || []} now={now} />)}</div>
      <nav className="pagination" aria-label="Poll pages">
        <Button variant="secondary" disabled={page === 1 || !polls.data.previous} onClick={() => update({ page: String(page - 1) }, true)}>Previous page</Button>
        <span aria-current="page">Page {page}</span>
        <Button variant="secondary" disabled={!polls.data.next} onClick={() => update({ page: String(page + 1) }, true)}>Next page</Button>
      </nav>
    </>}
  </section>
}
