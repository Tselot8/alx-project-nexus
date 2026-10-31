import { describe, expect, it } from 'vitest'
import { changedFields, editorValues, localDate, pollWrite, validateEditor } from './editor-model'
import { draftPoll } from './test-fixture'

describe('editor validation and strict writable contracts', () => {
  it('permits incomplete drafts but rejects incomplete publication', () => {
    const values = editorValues()
    expect(validateEditor(values, ['', ''], false)).toEqual({})
    expect(validateEditor(values, ['', ''], true)).toHaveProperty('question')
    expect(validateEditor({ ...values, question: 'A question?' }, ['Only one'], true)).toHaveProperty('options')
  })
  it.each([['Same', ' same '], ['Ａ', 'A'], ['', 'Valid']])('rejects blank or normalized duplicate answers %j', (...options) => {
    expect(validateEditor({ ...editorValues(), question: 'Question?' }, options, true)).toHaveProperty('options')
  })
  it.each([['0', '2'], ['1.5', '3'], ['2', '1'], ['1', '101']])('enforces numeric selection bounds (%s, %s)', (min, max) => {
    expect(Object.keys(validateEditor({ ...editorValues(), voting_mode: 'multiple', min_selections: min, max_selections: max }, ['A', 'B'], false)).length).toBeGreaterThan(0)
  })
  it('requires publication limits not to exceed options', () => {
    expect(validateEditor({ ...editorValues(), question: 'Question?', voting_mode: 'multiple', min_selections: '3', max_selections: '4' }, ['A', 'B'], true)).toHaveProperty('max_selections')
  })
  it('rejects long options and too many options without constraining draft completeness', () => {
    expect(validateEditor(editorValues(), ['a'.repeat(256)], false)).toHaveProperty('options')
    expect(validateEditor(editorValues(), Array(101).fill(''), false)).toHaveProperty('options')
  })
  it('rejects past deadlines, preserving unchanged historical closed dates', () => {
    const poll = draftPoll({ status: 'closed', expires_at: '2001-01-01T00:00:00.123Z' })
    expect(validateEditor(editorValues(poll), [], false, poll)).toEqual({})
    expect(validateEditor({ ...editorValues(poll), expires_at: '2000-01-01T00:00' }, [], false, poll)).toHaveProperty('expires_at')
    expect(validateEditor(editorValues(poll), ['A', 'B'], true, poll)).toHaveProperty('expires_at')
  })
  it('preserves timestamp precision and sends only writable fields', () => {
    const poll = draftPoll({ expires_at: '2035-01-01T10:15:37.123Z' })
    const write = pollWrite(editorValues(poll), poll)
    expect(write.expires_at).toBe(poll.expires_at)
    expect(write).not.toHaveProperty('id')
    expect(write).not.toHaveProperty('version')
    expect(write).not.toHaveProperty('created_by')
    expect(write).not.toHaveProperty('configuration_locked')
    expect(changedFields({ ...editorValues(poll), description: 'Changed' }, poll)).toEqual({ description: 'Changed' })
  })
  it('normalizes single-choice limits and optional values', () => {
    expect(pollWrite({ ...editorValues(), min_selections: '3', max_selections: '4' })).toMatchObject({ min_selections: 1, max_selections: null, category: null, expires_at: null })
    expect(localDate(null)).toBe('')
    expect(localDate('not a date')).toBe('')
  })
})
