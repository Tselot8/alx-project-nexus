import { useState } from 'react'
import type { PollDetail } from '../../api/contracts'
import { useServices, useSession } from '../../app/providers'
import { Button, Card, EmptyState, Feedback, Loading } from '../../ui/components'
import { resultsPotential, useResults } from './api'

function RestrictedResults({ poll }: { poll: PollDetail }) {
  return <Feedback>{poll.results_visibility === 'after_voting'
    ? 'Results are available only after your account has voted, even after this poll closes. A shared link does not establish participation.'
    : poll.results_visibility === 'after_closing'
    ? 'Results are available after voting closes. Reopening a poll hides them again.'
    : 'Results are not available to this account.'}</Feedback>
}
export function PollResultsPanel({ poll, now, scope, validating }: { poll: PollDetail; now: number; scope: string; validating: boolean }) {
  const snapshot = useSession()
  const [metric, setMetric] = useState<'participants' | 'selections'>('participants')
  const userId = snapshot.status === 'authenticated' ? snapshot.user.id : null
  return <Card className="results-card"><h2>Poll results</h2>
    {validating ? <Loading label="Checking results access…" /> : !resultsPotential(poll, userId, now) ? <RestrictedResults poll={poll} />
      : <ResultsReader poll={poll} scope={scope} authenticated={userId !== null} metric={metric} changeMetric={setMetric} />}
  </Card>
}
function ResultsReader({ poll, scope, authenticated, metric, changeMetric }: {
  poll: PollDetail; scope: string; authenticated: boolean; metric: 'participants' | 'selections'; changeMetric: (metric: 'participants' | 'selections') => void
}) {
  const services = useServices()
  const query = useResults(services, poll, scope, authenticated)
  function refresh() {
    for (const prefix of ['poll', 'ballot', 'poll-results']) {
      void services.queryClient.invalidateQueries({ queryKey: [prefix, poll.id] })
    }
  }
  if (query.isPending || query.isFetching) return <Loading label="Loading aggregate results…" />
  const data = query.data
  if (data?.kind === 'restricted') return <><RestrictedResults poll={poll} /><Button variant="quiet" onClick={refresh}>Check results access again</Button></>
  if (data?.kind === 'unavailable') return <Feedback>Results are unavailable. Reopen the original link if private access has ended.</Feedback>
  if (!data || data.kind !== 'ok') return <><Feedback tone="error">{data?.kind === 'error' && data.code === 'session'
    ? 'Your session ended. Sign in again to check results.'
    : data?.kind === 'error' && data.code === 'history' ? 'Results are temporarily unavailable while voting history is reconciled.'
    : 'Results could not be loaded or verified. No previous totals are shown.'}</Feedback>
    <Button variant="secondary" onClick={refresh}>Retry results</Button></>
  const results = data.results
  const percent = (value: number) => value.toLocaleString(undefined, { maximumFractionDigits: 2 }) + '%'
  return <>
    <dl className="results-totals"><div><dt>Unique participants</dt><dd>{results.total_participants.toLocaleString()}</dd></div>
      <div><dt>Total selections</dt><dd>{results.total_selections.toLocaleString()}</dd></div></dl>
    <fieldset className="metric-control"><legend>Show percentages by</legend>
      <label><input type="radio" name={'metric-' + poll.id} checked={metric === 'participants'} onChange={() => changeMetric('participants')} />Participants</label>
      <label><input type="radio" name={'metric-' + poll.id} checked={metric === 'selections'} onChange={() => changeMetric('selections')} />Selections</label>
    </fieldset>
    <p className="metadata">{metric === 'participants'
      ? 'Each option count divided by unique participants. ' + (poll.voting_mode === 'multiple' ? 'People can select several options, so these percentages can add up to more than 100%.' : 'Each participant contributes one selection.')
      : 'Each option count divided by total selections. Percentages add up to about 100%, allowing for rounding.'}</p>
    {results.total_participants === 0 && <EmptyState title="No votes yet.">There are no submitted selections in these results.</EmptyState>}
    <figure className="result-figure"><figcaption>Results by percentage of {metric}</figcaption>
      <div className="result-bars" aria-hidden="true">{results.options.map(option => {
        const value = metric === 'participants' ? option.percentage_of_participants : option.percentage_of_selections
        return <div className="result-bar-row" key={option.id}><div className="result-bar-label"><span>{option.option_text}</span><strong>{option.count.toLocaleString()} · {percent(value)}</strong></div>
          <div className="result-bar-track"><div style={{ width: value + '%' }} /></div></div>
      })}</div>
    </figure>
    <div className="results-table-scroll" role="region" aria-label="Aggregate results table" tabIndex={0}>
      <table className="results-table"><caption>Aggregate counts and both percentage measures. No voter identities are included.</caption>
        <thead><tr><th scope="col">Option</th><th scope="col">Selections</th><th scope="col">Participants %</th><th scope="col">Selections %</th></tr></thead>
        <tbody>{results.options.map(option => <tr key={option.id}><th scope="row">{option.option_text}</th><td>{option.count.toLocaleString()}</td>
          <td>{percent(option.percentage_of_participants)}</td><td>{percent(option.percentage_of_selections)}</td></tr>)}</tbody>
      </table>
    </div>
    <Button variant="quiet" onClick={refresh}>Refresh results</Button>
  </>
}
