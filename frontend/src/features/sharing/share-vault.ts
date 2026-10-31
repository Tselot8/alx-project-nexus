import type { ShareResolution } from '../../api/contracts'
import { ApiError, HttpClient, shareReadable } from '../../api/http'

const tokenPattern = /^[A-Za-z0-9_-]{43}$/
const uuid = '[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}'
export type CapturedShare = { token: string; expectedPoll: string | null } | { invalid: true } | null

/** Run before router/session effects, telemetry or other network requests. */
export function capturePrivateShare(browser: Pick<Window, 'location' | 'history'>): CapturedShare {
  const { hash, pathname, search } = browser.location
  if (!hash.startsWith('#share=')) return null
  browser.history.replaceState(browser.history.state, '', pathname + search)
  const params = new URLSearchParams(hash.slice(1))
  const token = params.get('share')
  const match = pathname.match(new RegExp('^/polls/(' + uuid + ')/?$', 'i'))
  if (!token || !tokenPattern.test(token) || params.size !== 1 || (pathname !== '/' && !match)) {
    return { invalid: true }
  }
  return { token, expectedPoll: match?.[1]?.toLowerCase() ?? null }
}

export class ShareVault {
  #grants = new Map<string, string>()
  constructor(private http: HttpClient) {}
  async resolve(captured: Exclude<CapturedShare, null>, signal?: AbortSignal): Promise<string> {
    if ('invalid' in captured) throw new ApiError(400, 'invalid_link', 'This private link is invalid.')
    const result = await this.http.request<ShareResolution>('/api/v2/shares/resolve/', {
      method: 'POST', body: { token: captured.token }, signal,
    })
    const id = result?.poll?.id
    if (typeof id !== 'string' || !new RegExp('^' + uuid + '$', 'i').test(id)
      || result.share?.poll_id !== id || result.share.header !== 'X-Poll-Share'
      || result.poll.visibility !== 'private'
      || (captured.expectedPoll && captured.expectedPoll !== id.toLowerCase())) {
      throw new ApiError(404, 'invalid_link', 'This private link is unavailable.')
    }
    signal?.throwIfAborted()
    this.#grants.set(id.toLowerCase(), captured.token)
    return id
  }
  credential(path: string, method: string) {
    if (!['GET', 'HEAD'].includes(method)) return undefined
    for (const [pollId, token] of this.#grants) {
      if (shareReadable(path, pollId)) return { pollId, token }
    }
    return undefined
  }
  clear() { this.#grants.clear() }
}
