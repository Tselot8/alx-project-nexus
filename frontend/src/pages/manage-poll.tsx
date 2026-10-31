import { useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router'
import { useServices, useSession } from '../app/providers'
import type { PollDetail } from '../api/contracts'
import { ApiError } from '../api/http'
import { creatorCommands, useCreatorPoll } from '../features/creator/api'
import { changedFields } from '../features/creator/editor-model'
import { PollEditor } from '../features/creator/poll-editor'
import { OptionsEditor } from '../features/creator/options-editor'
import { Sharing } from '../features/creator/sharing'
import { uuidPattern } from '../features/polls/api'
import { DateLabel, pollState, useNow } from '../features/polls/presentation'
import { ActionFeedback, Confirmation, useAction } from '../ui/workflow'
import { Button, Card, Feedback, Field, Loading } from '../ui/components'
import { NotFound } from './foundation'

type LifecycleAction = 'publish' | 'close' | 'reopen' | 'archive' | 'delete'
export function ManagePoll() {
  const services = useServices()
  const session = useSession()
  const { id = '' } = useParams()
  if (session.status !== 'authenticated') return null
  return <CreatorPoll key={session.user.id + ':' + services.session.generation + ':' + id} id={id} user={session.user.id} />
}
function CreatorPoll({ id, user }: { id: string; user: string }) {
  const services = useServices()
  const query = useCreatorPoll(services, id, user)
  if (!uuidPattern.test(id)) return <NotFound />
  if (query.isPending) return <Loading label="Loading poll management…" />
  if (query.isError) return <section className="page-section"><Card><h1>Poll management unavailable.</h1>
    <Feedback tone="error">{query.error instanceof ApiError && [403, 404].includes(query.error.status)
      ? 'Only the creator can manage an accessible poll.' : 'We could not load your poll.'}</Feedback>
    <Button onClick={() => { void query.refetch() }}>Retry management</Button><Link className="button button--quiet" to="/my-polls">My polls</Link>
  </Card></section>
  return <Workspace poll={query.data} />
}
function Workspace({ poll }: { poll: PollDetail }) {
  const services = useServices()
  const navigate = useNavigate()
  const location = useLocation()
  const action = useAction()
  const [confirm, setConfirm] = useState<LifecycleAction | null>(null)
  const [editorDirty, setEditorDirty] = useState(false)
  const [optionDirty, setOptionDirty] = useState(false)
  const [deadline, setDeadline] = useState('')
  const [noExpiration, setNoExpiration] = useState(false)
  const [reopenError, setReopenError] = useState<string[] | undefined>()
  const now = useNow()
  const heading = useRef<HTMLHeadingElement>(null)
  const blocked = action.busy || editorDirty || optionDirty
  async function transition() {
    if (!confirm || blocked) return
    const expires = deadline ? new Date(deadline) : null
    if (confirm === 'reopen' && !noExpiration && (!expires || !Number.isFinite(expires.getTime()) || expires.getTime() <= Date.now())) {
      setReopenError(['Choose a future closing date or explicitly choose no expiration.']); return
    }
    await action.run(async () => {
      const commands = creatorCommands(services)
      if (confirm === 'delete') { await commands.remove(poll.id); navigate('/my-polls', { replace: true, state: { notice: 'Draft deleted.' } }); return }
      await commands.transition(poll.id, confirm, confirm === 'reopen' ? { expires_at: noExpiration ? null : expires!.toISOString() } : {})
      setConfirm(null); setReopenError(undefined)
      requestAnimationFrame(() => heading.current?.focus())
    }, confirm === 'publish' ? 'Poll published.' : confirm === 'close' ? 'Poll closed.' : confirm === 'reopen' ? 'Poll reopened.' : 'Poll archived.')
  }
  const labels = { publish: 'Publish this poll?', close: 'Close voting?', reopen: 'Reopen this poll?', archive: 'Archive this poll permanently?', delete: 'Permanently delete this draft?' }
  return <section className="page-section creator-workspace">
    <div className="workspace-topline"><Link to="/my-polls">← My polls</Link><Link to={'/polls/' + poll.id}>View poll</Link></div>
    <div className="page-heading"><p className="eyebrow">Creator workspace</p><h1 tabIndex={-1} ref={heading}>{poll.question || 'Untitled draft'}</h1>
      <div className="poll-badges"><span className="pill">{pollState(poll, now)}</span><span className="pill pill--neutral">{poll.visibility === 'private' ? 'Private' : 'Public'}</span></div>
      <p className="metadata">Closing date: {poll.expires_at ? <DateLabel value={poll.expires_at} /> : 'No scheduled expiration'}</p>
    </div>
    {typeof location.state?.notice === 'string' && <Feedback>{location.state.notice}</Feedback>}
    <ActionFeedback action={action} />
    <div className="workspace-grid"><div className="form-stack">
      <PollEditor poll={poll} action={action} onDirty={setEditorDirty} save={async values => {
        let saved: PollDetail | null = null
        await action.run(async () => { saved = await creatorCommands(services).update(poll.id, changedFields(values, poll)) }, 'Poll settings saved.')
        return saved
      }} />
      <OptionsEditor poll={poll} action={action} onDirty={setOptionDirty} />
    </div><aside className="form-stack" aria-label="Poll management actions">
      <Card><h2>Poll lifecycle</h2>
        {(editorDirty || optionDirty) && <p role="status">Save or discard your edits before changing the poll lifecycle.</p>}
        <div className="form-stack">{poll.status === 'draft' && <>
          <Button disabled={blocked} onClick={() => setConfirm('publish')}>Publish poll</Button>
          {poll.configuration_editable === true && poll.configuration_locked === false && <Button variant="quiet" disabled={blocked} onClick={() => setConfirm('delete')}>Delete draft</Button>}
        </>}
        {poll.status === 'published' && <Button variant="secondary" disabled={blocked} onClick={() => setConfirm('close')}>Close poll</Button>}
        {poll.status === 'closed' && <Button variant="secondary" disabled={blocked} onClick={() => setConfirm('reopen')}>Reopen poll</Button>}
        {(poll.status === 'published' || poll.status === 'closed') && <Button variant="quiet" disabled={blocked} onClick={() => setConfirm('archive')}>Archive poll</Button>}
        {poll.status === 'archived' && <p>This poll cannot be restored or deleted.</p>}</div>
      </Card>
      {confirm && poll.status !== 'archived' && <Confirmation title={labels[confirm]} busy={action.busy} label={confirm === 'delete' ? 'Permanently delete draft' : 'Confirm ' + confirm}
        cancel={() => { setConfirm(null); setReopenError(undefined) }} confirm={() => { void transition() }}>
        <p>{confirm === 'archive' ? 'Archiving is permanent. The poll becomes read-only, leaves discovery, and cannot be restored.'
          : confirm === 'delete' ? 'The draft and its options will be permanently deleted.'
          : confirm === 'close' ? 'New and updated selections will no longer be accepted.'
          : confirm === 'publish' ? 'The backend will validate the question, options, limits, and closing date before publication.'
          : 'Voting opens again only after this explicit action. After-closing results will be hidden again.'}</p>
        {confirm === 'reopen' && <div className="form-stack">
          <Field label="New closing date" type="datetime-local" value={deadline} disabled={noExpiration || action.busy} error={reopenError} onChange={event => setDeadline(event.target.value)} />
          <label className="checkbox-label"><input type="checkbox" checked={noExpiration} disabled={action.busy} onChange={event => setNoExpiration(event.target.checked)} />Reopen with no expiration</label>
        </div>}
      </Confirmation>}
      {poll.visibility === 'private' && <Sharing poll={poll} />}
    </aside></div>
  </section>
}
