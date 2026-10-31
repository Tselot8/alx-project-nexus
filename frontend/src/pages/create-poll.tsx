import { useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { useServices } from '../app/providers'
import { ApiError } from '../api/http'
import { PollEditor } from '../features/creator/poll-editor'
import { creatorCommands } from '../features/creator/api'
import { pollWrite } from '../features/creator/editor-model'
import { ActionFeedback, Confirmation, useAction } from '../ui/workflow'
import { Feedback } from '../ui/components'

export function CreatePoll() {
  const services = useServices()
  const navigate = useNavigate()
  const action = useAction()
  const [uncertain, setUncertain] = useState(false)
  const [retryConfirmation, setRetryConfirmation] = useState(false)
  const created = useRef<string | null>(null)
  return <section className="page-section"><div className="page-heading"><p className="eyebrow">Create a poll</p>
    <h1>What would you like to ask?</h1><p className="page-lead">One good question. A space for every perspective.</p></div>
    <ActionFeedback action={action} />
    {uncertain && <Feedback tone="error">Draft creation could not be confirmed. It may already have been saved. Check My polls before starting another draft.
      <Link className="button button--secondary" to="/my-polls" target="_blank" rel="noopener noreferrer">Check My polls</Link>
      <button className="button button--quiet" onClick={() => setRetryConfirmation(true)}>Review another creation attempt</button></Feedback>}
    {retryConfirmation && <Confirmation title="Check for an existing draft before trying again" busy={action.busy} label="Allow another attempt" cancel={() => setRetryConfirmation(false)} confirm={() => { setRetryConfirmation(false); setUncertain(false) }}>
      <p>The previous request may have saved a draft. Check My polls first. Another attempt may create a duplicate; continue only after reviewing the saved polls.</p>
    </Confirmation>}
    <PollEditor blocked={uncertain} action={action} onDirty={() => {}} save={async (values, options, publish) => {
        await action.run(async () => {
          if (created.current) { navigate('/polls/' + created.current + '/manage'); return }
          const commands = creatorCommands(services)
          let poll
          try { poll = await commands.create({ ...pollWrite(values), options: options.map(option_text => ({ option_text })) }) }
          catch (error) { if (error instanceof ApiError && (error.status === 0 || error.status >= 500)) setUncertain(true); throw error }
          created.current = poll.id
          let notice = 'Draft saved.'
          if (publish) {
            try { await commands.transition(poll.id, 'publish'); notice = 'Poll published.' }
            catch (error) {
              if (error instanceof DOMException && error.name === 'AbortError') throw error
              notice = 'Draft saved, but publication was not confirmed. Review the current status before publishing again.'
            }
          }
          navigate('/polls/' + poll.id + '/manage', { replace: true, state: { notice } })
        })
        return null
      }} />
  </section>
}
