import type { PollDetail } from '../../api/contracts'
import type { PollWrite } from './api'
export interface EditorValues {
  question: string; description: string; category: string; visibility: PollWrite['visibility']; voting_mode: PollWrite['voting_mode']
  results_visibility: PollWrite['results_visibility']; min_selections: string; max_selections: string; expires_at: string
}
export function localDate(value: string | null) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16)
}
export function editorValues(poll?: PollDetail): EditorValues {
  return {
    question: poll?.question || '', description: poll?.description || '', category: poll?.category || '',
    visibility: poll?.visibility || 'public', voting_mode: poll?.voting_mode || 'single',
    results_visibility: poll?.results_visibility || 'immediate', min_selections: String(poll?.min_selections || 1),
    max_selections: poll?.max_selections == null ? '' : String(poll.max_selections), expires_at: localDate(poll?.expires_at || null),
  }
}
export const lockedFields = ['question', 'visibility', 'voting_mode', 'results_visibility', 'min_selections', 'max_selections'] as const
export function validateEditor(values: EditorValues, options: string[], publishing: boolean, original?: PollDetail): Record<string, string[]> {
  const errors: Record<string, string[]> = {}
  const min = Number(values.min_selections)
  const max = values.max_selections === '' ? null : Number(values.max_selections)
  if (values.question.length > 2000 || (publishing && !values.question.trim())) errors.question = ['Enter a question before publishing (up to 2,000 characters).']
  if (values.voting_mode === 'multiple') {
    if (!Number.isInteger(min) || min < 1 || min > 100) errors.min_selections = ['Minimum must be a whole number from 1 to 100.']
    if (max !== null && (!Number.isInteger(max) || max < min || max > 100)) errors.max_selections = ['Maximum must be at least the minimum and no greater than 100.']
    if (publishing && (min > options.length || (max !== null && max > options.length))) errors.max_selections = ['Selection limits cannot exceed the number of options.']
  }
  if (options.length > 100 || options.some(text => text.length > 255)) errors.options = ['Use at most 100 options, each up to 255 characters.']
  if (publishing) {
    const normalized = options.map(text => text.trim().normalize('NFKC').toLocaleLowerCase('en'))
    if (options.length < 2 || normalized.some(text => !text) || new Set(normalized).size !== normalized.length) errors.options = ['Provide at least two distinct, nonempty options.']
  }
  if (values.expires_at && (publishing || values.expires_at !== localDate(original?.expires_at || null))) {
    const time = new Date(values.expires_at).getTime()
    if (!Number.isFinite(time) || time <= Date.now()) errors.expires_at = ['Choose a future closing date or remove it.']
  }
  return errors
}
export function pollWrite(values: EditorValues, original?: PollDetail): PollWrite {
  return {
    question: values.question.trim(), description: values.description, category: values.category || null,
    visibility: values.visibility, voting_mode: values.voting_mode, results_visibility: values.results_visibility,
    min_selections: values.voting_mode === 'single' ? 1 : Number(values.min_selections),
    max_selections: values.voting_mode === 'single' || values.max_selections === '' ? null : Number(values.max_selections),
    // Keep the original precision when an unchanged existing datetime-local value is submitted.
    expires_at: values.expires_at === localDate(original?.expires_at || null) && original ? original.expires_at
      : values.expires_at ? new Date(values.expires_at).toISOString() : null,
  }
}
export function changedFields(values: EditorValues, original: PollDetail): Partial<PollWrite> {
  const next = pollWrite(values, original)
  const before = pollWrite(editorValues(original), original)
  return Object.fromEntries(Object.entries(next).filter(([name, value]) => before[name as keyof PollWrite] !== value))
}
