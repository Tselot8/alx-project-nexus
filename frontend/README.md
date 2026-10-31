# Project Nexus frontend — Milestone G

React + TypeScript foundation. All application code is inside `frontend/`;
Django stays at the repository root. Home, navigation, authentication and a
private current-user profile are functional. Poll discovery/detail, creation,
management, voting/results and profile editing are explicitly labeled previews
for Milestone H. No mock polls or participation statistics are presented.

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

## Private-link foundation

Future share links use /polls/<uuid>#share=<43-character-token>. main.tsx removes
the fragment with replaceState before rendering or bootstrapping authentication.
POST shares/resolve/ receives {token}; its response poll ID must match the link
and share.poll_id. X-Poll-Share is attached only to that poll's GET/HEAD detail,
option and results paths, never ballots, auth, mutations or unrelated polls.
The transport checks scope again and refuses redirects.

Capabilities are independent of login and remain only in the current tab's
memory. Reloading after fragment removal loses access: reopen the original
link. No analytics are present; future analytics must initialize after fragment
removal and must never collect private-link material. Full private-poll UX is H.
A valid link grants reads only; it does not grant voting permission.

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
