import { useId, useRef, useState } from 'react'
import { Link } from 'react-router'
import type { Ballot, PollDetail } from '../../api/contracts'
import { useServices, useSession } from '../../app/providers'
import { ApiError } from '../../api/http'
import { Button, Card, Feedback, Loading } from '../../ui/components'
import { ActionFeedback, useAction, useUnsavedChanges } from '../../ui/workflow'
import { ballotStamp, pollOpen, sameChoices, selectionErrors, submitBallot, useBallot } from './api'

export function SelectionGuidance({ poll }: { poll: PollDetail }) {
  return <p>{poll.voting_mode === 'single' ? 'Single choice · choose one option.'
    : 'Multiple choice · ' + (poll.max_selections === null ? 'at least ' + poll.min_selections
      : poll.min_selections === poll.max_selections ? 'exactly ' + poll.min_selections : poll.min_selections + '–' + poll.max_selections) + ' selections.'}</p>
}
function ClosedNotice({ poll }: { poll: PollDetail }) {
  return <Feedback>{poll.status === 'draft' ? 'This draft is visible only to its creator and is not open for voting.'
    : poll.status === 'archived' ? 'This poll is archived. It is permanently read-only.'
    : 'Voting is closed. New and updated selections are not accepted.'}</Feedback>
}
export function PollVoting({ poll, now, validating }: { poll: PollDetail; now: number; validating: boolean }) {
  const snapshot = useSession()
  const { session } = useServices()
  const eligible = snapshot.status === 'authenticated' && (poll.visibility === 'public' || snapshot.user.id === poll.created_by)
  if (eligible && poll.status !== 'draft') return <CurrentBallot key={snapshot.user.id + ':' + session.generation + ':' + poll.id}
    poll={poll} userId={snapshot.user.id} now={now} validating={validating} />
  const open = pollOpen(poll, now)
  return <Card><h2>Answer options</h2><SelectionGuidance poll={poll} />
    {poll.options.length ? <ol className="option-preview">{poll.options.map(option =>
      <li key={option.id}>{option.option_text || 'Empty draft option'}</li>)}</ol> : <p>No options have been added to this draft.</p>}
    {!open ? <ClosedNotice poll={poll} /> : poll.visibility === 'private' ? <Feedback>This private link provides read-only access. Only the creator can vote on private polls in this release.
      {snapshot.status !== 'authenticated' && <Link className="button button--secondary" to={'/login?returnTo=' + encodeURIComponent('/polls/' + poll.id)}>Sign in to your account</Link>}</Feedback>
      : <Feedback>Sign in to participate.<Link className="button button--secondary" to={'/login?returnTo=' + encodeURIComponent('/polls/' + poll.id)}>Sign in to participate</Link></Feedback>}
  </Card>
}
function CurrentBallot({ poll, userId, now, validating }: { poll: PollDetail; userId: string; now: number; validating: boolean }) {
  const services = useServices()
  const query = useBallot(services, poll, userId)
  if (!query.data) return <Card><h2>Your ballot</h2>{query.isPending ? <Loading label="Loading your saved selections…" />
    : <><Feedback tone="error">Your saved selections could not be checked. Voting is disabled until they can be verified.</Feedback>
      <Button onClick={() => { void query.refetch() }}>Retry saved selections</Button></>}</Card>
  if (query.data.kind === 'denied') return <Card><h2>Your ballot</h2>
    <Feedback tone="error">Your ballot is unavailable for this account. No selections can be submitted.</Feedback>
    <Button onClick={() => { void query.refetch() }}>Retry saved selections</Button></Card>
  return <BallotEditor poll={poll} saved={query.data.ballot} now={now} blocked={validating || query.isFetching || query.isError}
    readFailed={query.isError} reload={async () => {
      await services.queryClient.invalidateQueries({ queryKey: ['poll', poll.id] })
      const result = await query.refetch({ throwOnError: true })
      if (result.data?.kind !== 'ok') throw new ApiError(403, 'ballot_unavailable', 'Your saved ballot is unavailable.')
      return result.data.ballot
    }} />
}
function BallotEditor({ poll, saved, now, blocked, readFailed, reload }: {
  poll: PollDetail; saved: Ballot; now: number; blocked: boolean; readFailed: boolean; reload: () => Promise<Ballot>
}) {
  const services = useServices()
  const action = useAction()
  const [baseline, setBaseline] = useState(saved)
  const [selected, setSelected] = useState(saved.option_ids)
  const [errors, setErrors] = useState<string[]>([])
  const [reconcile, setReconcile] = useState(false)
  const summary = useRef<HTMLDivElement>(null)
  const group = useId()
  const dirty = !sameChoices(selected, baseline.option_ids)
  const stale = ballotStamp(saved) !== ballotStamp(baseline)
  const missing = selected.some(id => !poll.options.some(option => option.id === id)) || baseline.option_ids.some(id => !poll.options.some(option => option.id === id))
  const open = pollOpen(poll, now)
  const disabled = blocked || action.busy || !open || stale || missing || reconcile
  useUnsavedChanges(dirty)
  async function submit() {
    if (disabled) return
    const validation = pollOpen(poll) ? selectionErrors(poll, selected) : ['Voting is closed. Your selections were not submitted.']
    setErrors(validation)
    if (validation.length) { requestAnimationFrame(() => summary.current?.focus()); return }
    await action.run(async () => {
      try {
        const receipt = await submitBallot(services, poll, [...selected])
        setBaseline(receipt); setSelected(receipt.option_ids); setReconcile(false); setErrors([])
      } catch (error) {
        if (error instanceof ApiError && (error.status === 0 || error.status >= 500 || error.status === 409)) setReconcile(true)
        throw error
      }
    }, baseline.submitted ? 'Your ballot was updated. The complete selection set has replaced your previous choices.' : 'Your vote was saved.')
  }
  async function refreshSaved() {
    await action.run(async () => {
      const ballot = await reload()
      setBaseline(ballot); setSelected(ballot.option_ids); setErrors([]); setReconcile(false)
    }, 'Saved selections reloaded. Review them before making changes.')
  }
  return <Card><h2>Your ballot</h2><SelectionGuidance poll={poll} />
    <p>{baseline.submitted ? 'You have voted. Updates replace your complete selection set; you cannot withdraw your ballot.'
      : 'Choose your answers, then submit your complete ballot.'}</p>
    {baseline.submitted && <p className="pill">Saved ballot on file</p>}
    {(stale || missing) && <Feedback>Your saved ballot or the available options changed. Reload the latest saved selections before editing.</Feedback>}
    {readFailed && <Feedback tone="error">Saved selections could not be rechecked. Your unsaved choices are preserved, but submission is disabled.</Feedback>}
    {blocked && !readFailed && <Loading label="Checking the latest poll and ballot…" />}
    {reconcile && <Feedback>Reload your saved selections to check whether the last submission was accepted. No automatic retry was made.</Feedback>}
    <ActionFeedback action={action} />
    <div ref={summary} tabIndex={-1}>{!!errors.length && <Feedback tone="error">{errors.join(' ')}</Feedback>}</div>
    <form method="post" onSubmit={event => { event.preventDefault(); void submit() }} aria-label="Your vote">
      <fieldset disabled={disabled} className="vote-fieldset" aria-describedby={group + '-guidance' + (errors.length ? ' ' + group + '-error' : '')}>
        <legend>{poll.voting_mode === 'single' ? 'Choose one answer' : 'Choose your answers'}</legend>
        <p id={group + '-guidance'}>Your selections stay unsaved until you submit. {poll.voting_mode === 'multiple' && 'You can uncheck an option to choose a different set.'}</p>
        {!!errors.length && <p className="field-error" id={group + '-error'}>{errors.join(' ')}</p>}
        <div className="vote-options">{poll.options.map(option => {
          const checked = selected.includes(option.id)
          const savedChoice = baseline.submitted && baseline.option_ids.includes(option.id)
          const atLimit = poll.voting_mode === 'multiple' && poll.max_selections !== null && selected.length >= poll.max_selections
          return <label className="vote-option" key={option.id} data-selected={checked}>
            <input type={poll.voting_mode === 'single' ? 'radio' : 'checkbox'} name={group + '-choice'} value={option.id} checked={checked}
              disabled={!checked && atLimit} aria-invalid={!!errors.length || undefined} onChange={() => {
                setSelected(poll.voting_mode === 'single' ? [option.id] : checked ? selected.filter(id => id !== option.id) : [...selected, option.id])
                setErrors([]); action.clear()
              }} />
            <span>{option.option_text}</span>{savedChoice && <span className="saved-marker">Saved selection</span>}
          </label>
        })}</div>
      </fieldset>
      <p role="status" aria-live="polite">{selected.length} selected{dirty ? ' · Unsaved changes' : baseline.submitted ? ' · Saved selections' : ''}</p>
      {open && <Button type="submit" pending={action.busy} disabled={disabled || (baseline.submitted && !dirty)}>
        {baseline.submitted ? 'Update vote' : 'Submit vote'}</Button>}
    </form>
    <div className="action-row"><Button variant="quiet" disabled={action.busy} onClick={() => { void refreshSaved() }}>Reload saved selections</Button></div>
    {!open && <ClosedNotice poll={poll} />}
  </Card>
}
