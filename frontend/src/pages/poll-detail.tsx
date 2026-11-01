import { useSyncExternalStore } from 'react'
import { Link, useParams } from 'react-router'
import { useServices, useSession } from '../app/providers'
import { ApiError } from '../api/http'
import { useCategories, usePoll, uuidPattern } from '../features/polls/api'
import { CategoryLabel, DateLabel, pollState, useNow } from '../features/polls/presentation'
import { UnavailablePoll } from '../features/sharing/share-gate'
import { Button, Card, Feedback, Loading } from '../ui/components'
import { NotFound } from './foundation'
import { PollVoting } from '../features/participation/voting'
import { PollResultsPanel } from '../features/participation/results'

export function PollDetailPage() {
  const { id = '' } = useParams()
  const { api, shares, session } = useServices()
  const snapshot = useSession()
  const revision = useSyncExternalStore(shares.subscribe, shares.getSnapshot, shares.getSnapshot)
  const authenticated = snapshot.status === 'authenticated'
  const scope = (authenticated ? snapshot.user.id : snapshot.status) + ':' + session.generation + ':' + shares.scope(id) + ':' + revision
  const detail = usePoll(api, id, scope, authenticated, snapshot.status !== 'restoring')
  const categories = useCategories(api, 1)
  const now = useNow(detail.data?.expires_at)
  if (!uuidPattern.test(id)) return <NotFound />
  if (snapshot.status === 'restoring' || detail.isPending) return <Loading label="Loading poll…" />
  if (detail.isError) {
    if (detail.error instanceof ApiError && [403, 404].includes(detail.error.status)) return <UnavailablePoll />
    return <section className="page-section"><Card>
      <Feedback tone="error">{detail.error instanceof ApiError && detail.error.status === 401
        ? 'Your session has ended. Sign in again or retry as a guest.' : 'We could not load this poll. Please try again.'}</Feedback>
      <Button onClick={() => { void detail.refetch() }}>Retry poll</Button>
      <Link className="button button--quiet" to={'/login?returnTo=' + encodeURIComponent('/polls/' + id)}>Sign in</Link>
    </Card></section>
  }
  const poll = detail.data
  const owner = authenticated && snapshot.user.id === poll.created_by
  const state = pollState(poll, now)
  const shared = shares.has(id) && !owner
  return <section className="page-section detail-section">
    <Link className="back-link" to="/polls">← Explore polls</Link>
    <div className="poll-badges"><span className="pill">{state}</span><span className="pill pill--neutral">{poll.visibility === 'private' ? 'Private · unlisted' : 'Public poll'}</span></div>
    <h1>{poll.question || 'Untitled draft'}</h1>
    <div className="detail-metadata"><span><CategoryLabel id={poll.category} categories={categories.data?.results || []} /></span>
      {owner && <span>Created by you</span>}
      <span>Created <DateLabel value={poll.created_at} /></span></div>
    {poll.description && <p className="poll-description">{poll.description}</p>}
    <div className="detail-grid"><div>
      <PollVoting poll={poll} now={now} validating={detail.isFetching} />
      <div className="participation-notice"><PollResultsPanel key={scope + ':' + poll.id} poll={poll} now={now} scope={scope} validating={detail.isFetching} /></div>
    </div><aside aria-label="Poll information">
      <Card><h2>About this poll</h2>
        <dl className="poll-facts"><dt>Closing date</dt><dd>{poll.expires_at ? <DateLabel value={poll.expires_at} /> : 'No scheduled closing date'}</dd>
          <dt>Results policy</dt><dd>{poll.results_visibility === 'immediate' ? 'Immediately'
            : poll.results_visibility === 'after_voting' ? 'After voting · participation remains required after closing' : 'After closing · hidden again if reopened'}</dd></dl>
        {owner && <><p>You own this poll. Open the creator workspace to manage settings and lifecycle.</p>
          <Link to="/my-polls" className="button button--secondary">My polls workspace</Link>
          <Link to={'/polls/' + poll.id + '/manage'} className="button button--primary">Manage this poll</Link></>}
      </Card>
      {shared && <Feedback>Private access is active for this tab. Reopen the original shared link after a refresh.
        <Button variant="quiet" onClick={() => shares.revoke(id)}>End private access</Button></Feedback>}
    </aside></div>
  </section>
}
