import { useState } from 'react'
import type { PollDetail } from '../../api/contracts'
import { useServices, useSession } from '../../app/providers'
import { Button, Card, Feedback, Loading } from '../../ui/components'
import { Confirmation, useAction } from '../../ui/workflow'
import { creatorCommands, useShareStatus } from './api'

export function Sharing({ poll }: { poll: PollDetail }) {
  const services = useServices()
  const session = useSession()
  const user = session.status === 'authenticated' ? session.user.id : ''
  const status = useShareStatus(services, poll.id, user)
  const action = useAction()
  const [issued, setLink] = useState<{ url: string; generation: number } | null>(null)
  const link = status.isSuccess && status.data.active && status.data.generation === issued?.generation ? issued.url : ''
  const [confirm, setConfirm] = useState<'regenerate' | 'revoke' | null>(null)
  const [copied, setCopied] = useState(false)
  const [copyFailed, setCopyFailed] = useState(false)
  const allowed = poll.status === 'published' || poll.status === 'closed'
  async function change(operation: 'issue' | 'regenerate' | 'revoke') {
    if (operation !== 'revoke' && !allowed) return
    setLink(null); setCopied(false); setCopyFailed(false)
    await action.run(async () => {
      const issued = await creatorCommands(services).share(poll.id, operation)
      setLink(issued)
      setConfirm(null)
    }, operation === 'revoke' ? 'Private link revoked.' : 'New link created. Copy it now; it cannot be retrieved later.')
  }
  async function copy() {
    try { await navigator.clipboard.writeText(link); setCopied(true); setCopyFailed(false) }
    catch { setCopyFailed(true) }
  }
  return <Card><h2>Private sharing</h2><p>A shared link grants read-only access to this poll. It does not grant voting or management permissions.</p>
    {status.isPending ? <Loading label="Loading sharing status…" /> : status.isError ? <Feedback tone="error">Sharing status is unavailable.
      <Button variant="secondary" onClick={() => { void status.refetch() }}>Retry sharing status</Button></Feedback> : <>
      <p role="status">{status.data.active ? 'A private link is active.' : 'No private link is active.'}</p>
      <p>Only a newly issued link can be displayed. The server keeps a digest, not the original link.</p>
      <div className="action-row">{allowed && <Button disabled={action.busy || status.data.active} onClick={() => { void change('issue') }}>Issue private link</Button>}
        {allowed && status.data.active && <Button variant="secondary" disabled={action.busy} onClick={() => setConfirm('regenerate')}>Regenerate link</Button>}
        {status.data.active && <Button variant="quiet" disabled={action.busy} onClick={() => setConfirm('revoke')}>Revoke link</Button>}
      </div>
    </>}
    {poll.status === 'draft' && <Feedback>Publish this private poll before issuing a link.</Feedback>}
    {poll.status === 'archived' && <Feedback>Archived links can be revoked for security, but cannot be issued or regenerated.</Feedback>}
    {action.error && <Feedback tone="error">{action.error.status === 409 ? 'A link is already active. Reload sharing status and regenerate only if you want to replace it.'
      : 'The sharing change could not be confirmed. Reload sharing status before trying again.'}
      <Button variant="secondary" onClick={() => { void status.refetch() }}>Reload sharing status</Button></Feedback>}
    {action.message && <Feedback tone="success">{action.message}</Feedback>}
    {link && <div className="form-stack"><div className="field"><label htmlFor="new-share-link">New private link · shown once</label>
      <input id="new-share-link" type="text" readOnly value={link} autoComplete="off" onFocus={event => event.currentTarget.select()} /></div>
      <div className="action-row"><Button onClick={() => { void copy() }}>Copy private link</Button>
        <Button variant="quiet" onClick={() => setLink(null)}>Hide private link</Button></div>
      {copied && <Feedback tone="success">Link copied. Share it only with people you trust.</Feedback>}
      {copyFailed && <Feedback>Copy is unavailable. Select and copy the link from the field above.</Feedback>}
    </div>}
    {confirm && (confirm === 'revoke' || allowed) && <Confirmation title={confirm === 'regenerate' ? 'Replace the current private link?' : 'Revoke the private link?'} busy={action.busy}
      label={confirm === 'regenerate' ? 'Replace private link' : 'Revoke private link'} cancel={() => setConfirm(null)} confirm={() => { void change(confirm) }}>
      <p>The old link will stop working immediately after the server confirms this change. People holding it will lose future access.</p>
    </Confirmation>}
  </Card>
}
