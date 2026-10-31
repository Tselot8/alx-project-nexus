import { useRef, useState } from 'react'
import type { FormEvent } from 'react'
import type { PollDetail } from '../../api/contracts'
import { useServices } from '../../app/providers'
import { useCategories } from '../polls/api'
import { Button, Card, Feedback, Field } from '../../ui/components'
import { Confirmation, SelectField, TextareaField, useUnsavedChanges } from '../../ui/workflow'
import type { Action } from '../../ui/workflow'
import { editorValues, lockedFields, validateEditor } from './editor-model'
import type { EditorValues } from './editor-model'

export function CategorySelect({ value, change, disabled, error }: { value: string; change: (value: string) => void; disabled: boolean; error?: readonly string[] | undefined }) {
  const { api } = useServices()
  const [page, setPage] = useState(1)
  const categories = useCategories(api, page)
  return <div>
    <SelectField id="editor-category" label="Category" value={value} disabled={disabled} error={error} onChange={event => change(event.target.value)}>
      <option value="">No category</option>
      {value && !categories.data?.results.some(item => item.id === value) && <option value={value}>Current category (another list page)</option>}
      {categories.data?.results.map(category => <option value={category.id} key={category.id}>{category.name}</option>)}
    </SelectField>
    {categories.isPending && <p role="status">Loading categories…</p>}
    {categories.isError && <Feedback tone="error">Categories are unavailable.
      <Button type="button" variant="quiet" onClick={() => { void categories.refetch() }}>Retry categories</Button></Feedback>}
    {categories.data && (page > 1 || categories.data.next) && <div className="action-row">
      <Button type="button" variant="quiet" disabled={disabled || page === 1} onClick={() => setPage(page - 1)}>Previous categories</Button>
      <Button type="button" variant="quiet" disabled={disabled || !categories.data.next} onClick={() => setPage(page + 1)}>More categories</Button>
    </div>}
  </div>
}
export function PollEditor({ poll, action, save, onDirty, blocked = false }: {
  poll?: PollDetail; blocked?: boolean; action: Action; save: (values: EditorValues, options: string[], publish: boolean) => Promise<PollDetail | null>
  onDirty: (dirty: boolean) => void
}) {
  const [baseline, setBaseline] = useState(poll)
  const [values, setValues] = useState(() => editorValues(poll))
  const [options, setOptions] = useState(() => [{ key: 'first', text: '' }, { key: 'second', text: '' }])
  const [review, setReview] = useState(false)
  const [errors, setErrors] = useState<Record<string, string[]>>({})
  const summary = useRef<HTMLDivElement>(null)
  const optionInputs = useRef(new Map<string, HTMLInputElement>())
  const addButton = useRef<HTMLButtonElement>(null)
  const archived = poll?.status === 'archived'
  const locked = !!poll && (poll.configuration_editable !== true || poll.configuration_locked !== false)
  const stale = !!poll && baseline?.version !== poll.version
  const hasChanges = (nextValues: EditorValues, nextOptions = options) => JSON.stringify(nextValues) !== JSON.stringify(editorValues(baseline))
    || (!poll && (nextOptions.length !== 2 || nextOptions.some(option => option.text !== '')))
  const dirty = hasChanges(values)
  useUnsavedChanges(dirty)
  const fields = { ...action.error?.fieldErrors, ...errors }
  const change = <K extends keyof EditorValues>(key: K, value: EditorValues[K]) => {
    const next = { ...values, [key]: value }
    setValues(next); setReview(false); onDirty(hasChanges(next))
  }
  function validate(publishing: boolean) {
    const texts = poll ? poll.options.map(option => option.option_text) : options.map(option => option.text)
    const result = validateEditor(values, texts, publishing || (poll?.status === 'published' && !locked), baseline)
    if (stale) result.poll = ['The poll changed. Reload the editor before saving.']
    if (locked && lockedFields.some(key => values[key] !== editorValues(baseline)[key])) result.configuration = ['Locked settings have unsaved changes. Reload the editor to continue.']
    setErrors(result)
    if (Object.keys(result).length) requestAnimationFrame(() => summary.current?.focus())
    return Object.keys(result).length === 0
  }
  async function submit(publishing: boolean) {
    if (blocked || action.busy || archived || !validate(publishing)) return
    const saved = await save(values, options.map(option => option.text), publishing)
    if (saved) { setBaseline(saved); setValues(editorValues(saved)); setReview(false); onDirty(false) }
  }
  function reload() {
    setBaseline(poll); setValues(editorValues(poll)); setErrors({}); setReview(false); onDirty(false)
  }
  function addOption() {
    const key = crypto.randomUUID()
    const next = [...options, { key, text: '' }]
    setOptions(next); setReview(false); onDirty(hasChanges(values, next))
    requestAnimationFrame(() => optionInputs.current.get(key)?.focus())
  }
  function removeOption(index: number) {
    const next = options.filter((_, i) => index !== i)
    setOptions(next); setReview(false); onDirty(hasChanges(values, next))
    requestAnimationFrame(() => {
      const focus = next[Math.min(index, next.length - 1)]
      if (focus) optionInputs.current.get(focus.key)?.focus(); else addButton.current?.focus()
    })
  }
  return <Card className="editor-card">
    <h2>{poll ? 'Poll settings' : 'Build your question'}</h2>
    <p>Save explicitly. Drafts can be incomplete; publication requires a valid question and answer options.</p>
    {stale && <Feedback>The poll changed since you opened this editor. Reload to review its current settings.</Feedback>}
    <div ref={summary} tabIndex={-1}>{!!Object.keys(errors).length && <Feedback tone="error"><ul>{Object.entries(errors).map(([key, messages]) =>
      <li key={key}>{messages.join(' ')}</li>)}</ul></Feedback>}</div>
    {locked && <Feedback>{poll?.configuration_locked === null
      ? 'Historical voting status is unknown. Configuration is locked for safety.'
      : 'Voting or historical evidence locks the question, options, privacy, voting mode, limits, and results policy permanently.'}</Feedback>}
    <form method="post" aria-label={poll ? 'Edit poll settings' : 'Create poll'} onSubmit={(event: FormEvent) => { event.preventDefault(); void submit(false) }}>
      <fieldset disabled={action.busy || archived || review} className="form-stack">
        <legend className="sr-only">Poll configuration</legend>
        <fieldset disabled={locked} className="form-stack locked-settings"><legend>Question and voting rules{locked ? ' · locked' : ''}</legend>
          <Field label="Question" name="question" maxLength={2000} value={values.question} error={fields.question} onChange={event => change('question', event.target.value)} />
          <div className="form-columns">
            <SelectField id="visibility" label="Visibility" value={values.visibility} error={fields.visibility} onChange={event => change('visibility', event.target.value as EditorValues['visibility'])}>
              <option value="public">Public · discoverable</option><option value="private">Private · shared link only</option></SelectField>
            <SelectField id="voting-mode" label="Voting mode" value={values.voting_mode} error={fields.voting_mode} onChange={event => change('voting_mode', event.target.value as EditorValues['voting_mode'])}>
              <option value="single">Single choice</option><option value="multiple">Multiple choice</option></SelectField>
          </div>
          {values.voting_mode === 'multiple' && <div className="form-columns">
            <Field label="Minimum selections" type="number" min={1} max={100} step={1} value={values.min_selections} error={fields.min_selections} onChange={event => change('min_selections', event.target.value)} />
            <Field label="Maximum selections" type="number" min={1} max={100} step={1} value={values.max_selections} hint="Leave blank for no additional limit." error={fields.max_selections} onChange={event => change('max_selections', event.target.value)} />
          </div>}
          <SelectField id="results-policy" label="Results visibility" value={values.results_visibility} error={fields.results_visibility} onChange={event => change('results_visibility', event.target.value as EditorValues['results_visibility'])}>
            <option value="immediate">Immediately</option><option value="after_voting">After voting</option><option value="after_closing">After closing</option></SelectField>
          <p className="metadata">After voting requires participation even after closure. Reopening hides after-closing results again.</p>
        </fieldset>
        <TextareaField id="description" label="Description (optional)" rows={4} maxLength={10000} value={values.description} error={fields.description} onChange={event => change('description', event.target.value)} />
        <CategorySelect value={values.category} disabled={action.busy || !!archived} error={fields.category} change={value => change('category', value)} />
        <Field label="Closing date (optional)" type="datetime-local" value={values.expires_at} error={fields.expires_at} hint="Your local time. Changing this date never reopens a closed poll." onChange={event => change('expires_at', event.target.value)} />
        {!poll && <fieldset className="form-stack"><legend>Answer options</legend>
          <p id="options-hint">Add up to 100 options. Publishing requires at least two distinct, nonempty answers.</p>
          {fields.options && <p className="field-error" role="alert">{fields.options.join(' ')}</p>}
          {options.map((option, index) => <div className="option-edit-row" key={option.key}>
            <div className="field"><label htmlFor={'option-' + option.key}>Option {index + 1}</label>
              <input id={'option-' + option.key} ref={node => { if (node) optionInputs.current.set(option.key, node); else optionInputs.current.delete(option.key) }}
                maxLength={255} value={option.text} aria-describedby="options-hint" aria-invalid={!!fields.options || undefined}
                onChange={event => { const next = options.map(item => item.key === option.key ? { ...item, text: event.target.value } : item); setOptions(next); setReview(false); onDirty(hasChanges(values, next)) }} /></div>
            <Button type="button" variant="quiet" aria-label={'Remove option ' + (index + 1)} onClick={() => removeOption(index)}>Remove</Button>
          </div>)}
          <button ref={addButton} type="button" className="button button--secondary" disabled={options.length >= 100} onClick={addOption}>Add option</button>
        </fieldset>}
        {!archived && <div className="action-row">
          <Button type="submit" pending={action.busy} disabled={stale || blocked}>{poll ? 'Save settings' : 'Save draft'}</Button>
          {!poll && <Button type="button" variant="secondary" disabled={action.busy || blocked} onClick={() => { if (validate(true)) setReview(true) }}>Review & publish</Button>}
          {poll && <Button type="button" variant="quiet" disabled={action.busy} onClick={reload}>Reload editor / discard changes</Button>}
        </div>}
      </fieldset>
    </form>
    {!poll && review && !blocked && <Confirmation title="Review and publish" busy={action.busy} label="Create and publish poll" cancel={() => setReview(false)} confirm={() => { void submit(true) }}>
      <p><strong>{values.question}</strong></p><ul>{options.map(option => <li key={option.key}>{option.text}</li>)}</ul>
      <p>{values.visibility === 'public' ? 'Public and discoverable.' : 'Private and unlisted.'} A draft is saved first, then published. If publishing fails, your saved draft remains available.</p>
    </Confirmation>}
    {archived && <Feedback>This archived poll is permanently read-only.</Feedback>}
  </Card>
}
