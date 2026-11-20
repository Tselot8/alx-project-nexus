import ballotGarden from '../assets/ballot-garden.svg'
import conversationPapers from '../assets/conversation-papers.svg'
import ballotGardenDark from '../assets/ballot-garden-dark.svg'
import conversationPapersDark from '../assets/conversation-papers-dark.svg'
import { useTheme } from './theme-control'

export function BallotArtwork({ compact = false }: { compact?: boolean }) {
  const dark = useTheme().endsWith(':dark')
  const source = compact ? (dark ? conversationPapersDark : conversationPapers) : (dark ? ballotGardenDark : ballotGarden)
  return <img className={compact ? 'ballot-artwork ballot-artwork--compact' : 'ballot-artwork'}
    src={source} alt="" aria-hidden="true" decoding="async" />
}
export function NexusMark() {
  return <svg className="brand-mark" viewBox="0 0 36 36" fill="none" aria-hidden="true" focusable="false">
    <path d="m4 15 14-7 14 7v16H4V15Z" fill="currentColor" />
    <path d="m10 3 18 3-2 17-18-3 2-17Z" fill="var(--yellow)" stroke="currentColor" strokeWidth="2" />
    <path d="m13 12 4 4 7-7M8 23l20 3" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
}
export function ArrowMark({ diagonal = false }: { diagonal?: boolean }) {
  return <svg className="arrow-mark" viewBox="0 0 24 24" fill="none" aria-hidden="true" focusable="false">
    <path d={diagonal ? 'M6 18 18 6M6 6h12v12' : 'M4 12h15m-6-6 6 6-6 6'}
      stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
}
export function PaperMark() {
  return <svg className="paper-mark" viewBox="0 0 56 64" fill="none" aria-hidden="true" focusable="false">
    <path d="M7 4h30l13 13v43H7V4Z" fill="var(--periwinkle)" stroke="currentColor" strokeWidth="2" />
    <path d="M37 4v14h13M17 34l7 8 15-16M17 49h20" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
}
