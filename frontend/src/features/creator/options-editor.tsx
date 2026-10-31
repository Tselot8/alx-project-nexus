import { useRef, useState } from 'react'
import type { PollDetail } from '../../api/contracts'
import { ApiError } from '../../api/http'
import { useServices } from '../../app/providers'
import { Button, Card, Feedback } from '../../ui/components'
import { Confirmation, useUnsavedChanges } from '../../ui/workflow'
import type { Action } from '../../ui/workflow'
import { creatorCommands } from './api'

export function OptionsEditor({ poll, action, onDirty }: { poll: PollDetail; action: Action; onDirty: (dirty: boolean) => void }) {
  const services = useServices()
  const [editing, setEditing] = useState<string | null>(null)
  const [text, setText] = useState('')
  const [initial, setInitial] = useState('')
  const [remove, setRemove] = useState<string | null>(null)
  const [uncertain, setUncertain] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  const locked = poll.configuration_editable !== true || poll.configuration_locked !== false || poll.status === 'archived'
  useUnsavedChanges(editing === 'new' || (editing !== null && text !== initial))
  function begin(id: string, value: string) {
    setEditing(id); setText(value); setInitial(value); onDirty(id === 'new')
    requestAnimationFrame(() => input.current?.focus())
  }
  async function save() {
    if (locked || !editing || uncertain) return
    const ok = await action.run(async () => {
      try { await creatorCommands(services).option(poll.id, text, editing === 'new' ? undefined : editing) }
      catch (error) {
        if (editing === 'new' && error instanceof ApiError && (error.status === 0 || error.status >= 500)) setUncertain(true)
        throw error
      }
    }, 'Option saved.')
    if (ok) { setEditing(null); onDirty(false); requestAnimationFrame(() => heading.current?.focus()) }
  }
  return <Card><h2 ref={heading} tabIndex={-1}>Answer options</h2>
    <p>Each option is saved separately. Published polls must remain valid after every change; close the poll first for changes that need intermediate incomplete options.</p>
    {locked && <Feedback>Option editing is locked by voting history or archival.</Feedback>}
    <ul className="managed-options">{poll.options.map(option => <li key={option.id}>
      <span>{option.option_text || 'Empty draft option'}</span>
      {!locked && <div className="action-row"><Button variant="quiet" disabled={action.busy || !!editing} onClick={() => begin(option.id, option.option_text)}>Edit option</Button>
        <Button variant="quiet" disabled={action.busy || !!editing || (poll.status === 'published' && poll.options.length <= 2)} onClick={() => setRemove(option.id)} aria-label={'Remove ' + (option.option_text || 'empty option')}>Remove</Button></div>}
    </li>)}</ul>
    {!locked && !editing && <Button variant="secondary" disabled={action.busy || poll.options.length >= 100} onClick={() => begin('new', '')}>Add option</Button>}
    {editing && !locked && <form method="post" className="form-stack" aria-label="Edit answer option" onSubmit={event => { event.preventDefault(); void save() }}>
      <div className="field"><label htmlFor="managed-option">Option text</label><input id="managed-option" ref={input} value={text} maxLength={255} required={poll.status === 'published'} disabled={action.busy || uncertain}
        aria-describedby={action.error?.fieldErrors.option_text ? 'option-error' : undefined} aria-invalid={!!action.error?.fieldErrors.option_text || undefined}
        onChange={event => { setText(event.target.value); onDirty(editing === 'new' || event.target.value !== initial) }} />
        {action.error?.fieldErrors.option_text && <span className="field-error" id="option-error">{action.error.fieldErrors.option_text.join(' ')}</span>}</div>
      <div className="action-row"><Button type="submit" pending={action.busy} disabled={uncertain}>Save option</Button><Button type="button" variant="quiet" disabled={action.busy || uncertain} onClick={() => { setEditing(null); onDirty(false); heading.current?.focus() }}>Cancel option edit</Button></div>
    </form>}
    {uncertain && <Feedback tone="error">The new option may already have been saved. Reload the options and review them before adding it again.
      <Button variant="secondary" disabled={action.busy} onClick={() => {
        void action.run(async () => {
          await services.queryClient.refetchQueries({ queryKey: ['creator-poll', poll.id] }, { throwOnError: true })
          setUncertain(false); setEditing(null); onDirty(false)
        }, 'Options reloaded. Review the list before adding another option.')
      }}>Reload options</Button>
    </Feedback>}
    {remove && !locked && <Confirmation title="Remove this option?" busy={action.busy} label="Remove option" cancel={() => { setRemove(null); heading.current?.focus() }} confirm={() => {
      void action.run(async () => { await creatorCommands(services).removeOption(poll.id, remove); setRemove(null); requestAnimationFrame(() => heading.current?.focus()) }, 'Option removed.')
    }}><p>The option will be deleted. The backend will reject changes that make a published poll invalid.</p></Confirmation>}
    {editing && locked && <Feedback>Your unsaved option can no longer be saved because the configuration is now locked.
      <Button variant="quiet" onClick={() => { setEditing(null); onDirty(false); heading.current?.focus() }}>Discard option edit</Button></Feedback>}
    <p className="metadata">Option ordering is not editable.</p>
  </Card>
}
