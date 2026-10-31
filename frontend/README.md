# Project Nexus frontend — Milestones G and H1

React + TypeScript application inside frontend/; Django stays at the repository
root. Home, public discovery, poll detail, private shared-link reading,
authentication and the private current-user profile are functional. Creation,
management, voting/results and profile editing remain labeled previews for
later milestones. No fabricated polls or participation statistics are shown.

## Local development

Use Node 22.14+ with npm. On Windows PowerShell, use `npm.cmd` if execution
policy blocks `npm.ps1`; no policy change is needed. Dependencies are pinned
in package.json and package-lock.json. React Router 7, TypeScript 6.0 and
jsdom 29 match this runtime and their tooling peer requirements.

From this directory:

```text
npm ci
npm run dev
```

Vite listens only on localhost:5173 with strict port selection. Start Django
separately using the previously configured `alx_project_nexus.settings_local`
and its approved isolated local PostgreSQL service. This milestone does not
start Django/Docker or run migrations.

Copy `.env.example` to ignored `.env.local` only if the Django proxy port
needs changing. `NEXUS_PROXY_TARGET` defaults to http://127.0.0.1:8000 and
is restricted to loopback hosts; it is server-only, not a VITE browser variable.
Vite reads frontend environment files only, never the root production .env.

All browser API calls use /api/v2/ on the frontend origin. The proxy preserves
Origin and Host; local Django must allow localhost and explicitly trust
http://localhost:5173 for CSRF (as in the existing local environment example).
Do not solve proxy issues with wildcard CORS or production DEBUG changes.
A development HTTP server requires the existing explicit local cookie settings;
production refresh cookies remain Secure and HttpOnly.

## Contracts and security

Source of truth: accounts/v2_urls.py, v2_views.py, v2_serializers.py and
polls/v2_urls.py, v2_views.py, v2_serializers.py in the backend.

- GET auth/csrf/ returns csrf_token. Login/register POST email/password
  (registration also username), returning user/access/expires_in/csrf_token.
- POST auth/refresh/ uses the backend-managed nexus_v2_refresh_token cookie
  scoped to /api/v2/auth/ and returns access/expires_in only. GET auth/me/
  returns {user}. POST auth/logout/ revokes the cookie session and returns 204.
- Account fields are id, username, email and profile {bio, location}. Identity
  changes, email changes and privileged fields have no editable frontend input.
- Cookie operations use X-CSRFToken, including login/register. After a
  CSRF-specific 403, bootstrap and retry once; other failures are not replayed.
- Access/CSRF values and share capabilities stay in memory. No browser storage,
  query persistence, token logging, credential-bearing URLs or refresh-token
  JSON handling is implemented. Authentication bypasses Query's mutation cache.
- Refresh is single-flight, with one retry of protected 401 requests. Near-expiry
  access tokens refresh on demand. Web Locks serialize cookie operations across
  supporting same-origin tabs. Without Web Locks, coordination is per tab;
  a losing refresh fails closed and can require signing in again.
- Cookie mutations complete in order; they are not aborted mid-rotation. Epoch
  fences prevent stale responses from reviving a logged-out or changed account.
  Logout clears local identity/cache immediately; a failed server revocation is
  explicitly reported for retry. Refresh re-reads me to detect account changes.
- Protected data responses from an obsolete identity are discarded. Query
  caches clear on authentication changes. Public queries pass AbortSignal.
  Route guards are navigation aids; Django authorizes every protected request.
- HTTP redirects are rejected. Requests cannot send credentials off-origin or
  outside /api/v2/. Errors follow {error:{code,details}} and never retain request
  objects, passwords or raw network diagnostics.

## Private-link reading

Private share links use /polls/<uuid>#share=<43-character-token>. main.tsx removes
the fragment with replaceState before rendering or bootstrapping authentication.
POST shares/resolve/ receives {token}; its response poll ID must match the link
and share.poll_id. X-Poll-Share is attached only to that poll's GET/HEAD detail,
option and results paths, never ballots, auth, mutations or unrelated polls.
The transport checks scope again and refuses redirects.

Capabilities are independent of login and remain only in the current tab's
memory. Reloading after fragment removal loses access: reopen the original
link. No analytics are present; future analytics must initialize after fragment
removal and must never collect private-link material. Invalid/revoked links use the same unavailable screen as missing polls.
A valid link grants reads only; it does not grant voting permission.

## Discovery and detail contracts

- Public discovery uses q (question/description, up to 200 characters),
  category (UUID), status (published/closed), sort
  (newest/oldest/closing_soon), and page. The backend returns effective closed
  status for expired published polls and excludes private/draft/archived polls.
- Search is submitted explicitly; submitted search/filter/page state is in the
  URL and works with browser back/forward. Changed filters reset page to 1.
  Replaced requests are cancelled and no previous search results are retained.
- Pagination uses backend next/previous availability but computes local page
  numbers; it never follows response URLs. Categories are also paginated:
  More categories/Previous categories browse all choices without eager loading.
  Names outside the loaded category page are explicitly marked not loaded.
- Home shows up to three actual records from the newest public list. Cards do
  not infer creator names, vote counts or engagement fields missing from the API.
- Detail uses the real options, limits, lifecycle, expiration and results-policy
  fields. Options are read-only text; no voting or results requests are made.
  Results counts are neither rendered nor inferred. Creator navigation leads
  to the existing workspace preview, never an unimplemented management route.
- Detail query keys include user/session and share revision (never credentials).
  Details revalidate on mount/focus and are removed when unobserved. Changing or
  ending a share clears all detail queries and fences stale in-flight responses.
  A denied detail read revokes its local grant; an expected results-policy 403
  does not revoke otherwise valid poll access.
- The fragment gate suspends page data loading until resolution succeeds,
  including links opened at the home URL or through client navigation. Initial
  fragments are stripped before bootstrap; in-app fragments are stripped in a
  layout effect. Resolution failures never display backend diagnostic bodies.
- Share capability remains independent of login in tab memory, but data caches
  clear across identity changes. No private detail data is reused by a new
  identity or a replaced share session. End private access clears the grant.
  Revocation is checked on subsequent requests/focus; previously viewed content
  cannot be recalled before a server recheck. No background results cache exists.

## Dependency security

A targeted minimatch 11.0.1 override fixes the development lint tree's
[GHSA-g3hv-75wg-m249](https://github.com/advisories/GHSA-g3hv-75wg-m249).
The upstream lint packages still request an affected older major. Keep the
override until they consume a patched release; do not downgrade ESLint or
disable lint rules to work around npm audit. The complete lint/type/test/build
gates verify compatibility with this patched dependency.

## Quality gates

```text
npm ci
npm run lint
npm run typecheck
npm test
npm run build
git diff --check
```

Vitest/React Testing Library use mocked fetch responses with no Django, database
or production dependency. Tests cover auth, CSRF, refresh/logout races, private
scope, cache isolation, query cancellation, routing and keyboard navigation.
axe checks semantics and token tests check palette contrast. Full visual
contrast, zoom, real-browser layout and assistive
technology still warrant manual release review. CSS targets WCAG 2.2 AA with
visible focus, reduced motion, text labels and generous touch targets.

The existing GitHub workflow remains backend-only. Frontend quality gates run
locally here; adding frontend CI needs a separate reviewed workflow change.

## Provider-independent release requirements

Serve the built dist/ over HTTPS with a same-origin /api/ reverse proxy to
Django, preserve the backend cookie path/flags and configure explicit trusted
origins/hosts. SPA fallback must serve index.html for frontend routes but never
swallow /api/ errors. Vite preview is not a production server.

No deployment configuration was changed. Existing backend release/cutover gates
still apply. Hosting must provide suitable CSP/frame protections and avoid
logging sensitive headers/bodies; this foundation includes a no-referrer meta
policy and no external fonts/assets.

References: [Vite](https://vite.dev/guide/),
[React Router](https://reactrouter.com/start/declarative/installation),
[TanStack Query](https://tanstack.com/query/latest/docs/framework/react/overview).
