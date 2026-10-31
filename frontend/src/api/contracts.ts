/** Mirrors the current v2 serializers, not the legacy /api/ contracts. */
export interface Account {
  id: string
  username: string
  email: string
  profile: { bio: string | null; location: string | null }
}
export interface SessionResponse {
  user: Account
  access: string
  expires_in: number
  csrf_token: string
}
export interface RefreshResponse { access: string; expires_in: number }
export interface Credentials { email: string; password: string }
export interface Registration extends Credentials { username: string }
export interface Paginated<T> {
  count: number
  next: string | null
  previous: string | null
  results: T[]
}
export interface Category { id: string; name: string; description: string | null }
export type PollStatus = 'draft' | 'published' | 'closed' | 'archived'
export interface PollSummary {
  id: string
  question: string
  description: string | null
  category: string | null
  created_by: string
  visibility: 'public' | 'private'
  voting_mode: 'single' | 'multiple'
  status: PollStatus
  expires_at: string | null
  created_at: string
  version?: number
}
export interface PollDetail extends PollSummary {
  options: { id: string; option_text: string }[]
  results_visibility: 'immediate' | 'after_voting' | 'after_closing'
  min_selections: number
  max_selections: number | null
  configuration_locked?: boolean | null
  configuration_editable?: boolean
  updated_at?: string
}
export interface Ballot {
  poll_id: string
  option_ids: string[]
  submitted_at: string | null
  updated_at: string | null
  submitted: boolean
}
export interface PollResults {
  poll_id: string
  question: string
  authority: 'bridge' | 'ballots'
  total_participants: number
  total_selections: number
  options: {
    id: string
    option_text: string
    count: number
    percentage_of_participants: number
    percentage_of_selections: number
  }[]
}
export interface ShareResolution {
  poll: PollDetail
  share: { poll_id: string; header: 'X-Poll-Share' }
}
