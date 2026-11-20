import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const tokens = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'tokens.css'), 'utf8')

const dark = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'dark.css'), 'utf8')

function color(name: string, source = tokens) {
  const value = source.split('--' + name + ':')[1]?.trim().slice(0, 7)
  if (!value || !/^#[a-f0-9]{6}$/i.test(value)) throw new Error('Missing design token: ' + name)
  return value
}
function luminance(hex: string) {
  const channels = [1, 3, 5].map(start => parseInt(hex.slice(start, start + 2), 16) / 255)
    .map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4)
  return .2126 * channels[0]! + .7152 * channels[1]! + .0722 * channels[2]!
}
function contrast(first: string, second: string) {
  const a = luminance(first), b = luminance(second)
  return (Math.max(a, b) + .05) / (Math.min(a, b) + .05)
}
describe('Civic editorial palette contrast', () => {
  it.each(['background', 'surface'])('meets normal-text contrast on %s', background => {
    for (const foreground of ['text', 'muted', 'primary', 'accent', 'danger']) {
      expect(contrast(color(foreground), color(background))).toBeGreaterThanOrEqual(4.5)
    }
  })
  it.each(['periwinkle', 'coral', 'teal', 'yellow', 'paper'])('keeps ink readable on the %s accent', background => {
    expect(contrast(color('text'), color(background))).toBeGreaterThanOrEqual(4.5)
  })
  it('meets control/focus contrast and inverse primary-button contrast', () => {
    expect(contrast(color('control-border'), color('surface'))).toBeGreaterThanOrEqual(3)
    expect(contrast(color('primary'), color('surface'))).toBeGreaterThanOrEqual(4.5)
    expect(contrast(color('primary-hover'), color('surface'))).toBeGreaterThanOrEqual(4.5)
  })
})


describe('Editorial dark palette contrast', () => {
  it.each(['background', 'surface', 'paper', 'surface-high', 'selection'])('keeps body text and accents readable on %s', background => {
    for (const foreground of ['text', 'muted', 'primary', 'accent', 'danger']) {
      expect(contrast(color(foreground, dark), color(background, dark))).toBeGreaterThanOrEqual(4.5)
    }
  })
  it('keeps controls, focus, buttons and disabled labels distinguishable', () => {
    expect(contrast(color('control-border', dark), color('paper', dark))).toBeGreaterThanOrEqual(3)
    expect(contrast(color('primary', dark), color('surface-high', dark))).toBeGreaterThanOrEqual(3)
    expect(contrast(color('ink', dark), color('primary', dark))).toBeGreaterThanOrEqual(4.5)
    expect(contrast(color('ink', dark), color('primary-hover', dark))).toBeGreaterThanOrEqual(4.5)
    expect(contrast(color('disabled-text', dark), color('disabled', dark))).toBeGreaterThanOrEqual(4.5)
    for (const fill of ['coral', 'teal', 'yellow']) expect(contrast(color(fill, dark), '#3D4C60')).toBeGreaterThanOrEqual(3)
  })
})
