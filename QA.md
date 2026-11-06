# Milestone J QA and release gates

## Confirmed findings and corrections

| Finding | Correction and regression evidence |
| --- | --- |
| Legacy login, refresh and registration aliases bypassed the v2 abuse budgets. | Reuse the same connection-address throttle scopes across both API generations. Five regression tests failed before the correction, then passed. Spoofed forwarding headers cannot reset the budget. Excess requests intentionally receive 429 with Retry-After. |
| Legacy token responses could be cached. | Mark legacy authentication/registration responses never-cache, including no-store. Preserve successful JSON contracts. |
| Anonymous session restoration could clear active discovery queries and leave Explore loading indefinitely. | Discovery/category hooks subscribe to session changes and rebuild removed query observers. A deterministic delayed-response regression failed before the fix; stale requests remain cancelled and private cache clearing is preserved. Existing hook assertions use the real application providers. |
| Enlarged text could push desktop header actions outside the viewport. | Let the header wrap rather than forcing navigation onto one line. Real Chrome QA checks overflow, contrast and 200% CSS text scaling. |
| The persistent local stack had no safe one-command startup. | Add scripts/start_local.py: load ignored .env.local without interpolation, remove inherited production/test overrides, select settings_local, check database/migration state read-only, then start owned loopback servers. Six configuration tests cover fail-closed behavior. |

No polling/authentication architecture, model, migration, dependency, production
setting, Docker configuration or static asset was changed. Historical credentials
were not copied into examples. The user's existing local credentials and data
remain outside Git.

## Executed verification results

- Frontend: npm ci, ESLint, strict application/E2E TypeScript, **271 unit tests**
  and production build passed. npm ci reported zero known npm vulnerabilities.
- Backend: **270 tests and 140 subtests passed**, including all 27 PostgreSQL
  concurrency cases. Django system checks and makemigrations --check --dry-run
  passed with no changes. CI-equivalent flake8 (plus scripts/integration) passed.
- Full-stack: **16 integration checks passed**, including the original four
  Chrome journeys and six new desktop/tablet/mobile QA journeys. No checks
  were skipped. Automated axe audits reported no violations in those states.
  A separate final mobile rerun also passed the added 320-CSS-pixel reflow check.
- Startup --check/--smoke passed against the existing persistent development
  database. Only owned Django/Vite processes were started and stopped.
- git diff --check passed. Models, migrations, settings, dependencies, CI/Docker
  configuration and all 197 tracked static assets remain unchanged.

One pre-existing drf-yasg Swagger renderer deprecation warning remains. It did
not fail checks and was not suppressed. During development, focused failures
exposed the issues above; test-selector/provider fixtures were corrected without
removing existing assertions. The final full acceptance run passed.

## Verification scope

Run `python -B scripts/verify_fullstack.py` for the complete gate, and the
CI-equivalent Python lint command in [integration/README.md](integration/README.md).
The harness uses an ownership-labelled tmpfs PostgreSQL instance, fresh test
accounts/polls, test settings, a same-origin Vite proxy, and real Chrome. It cleans
up only its own resources and checks pre-existing Docker inventories.

Backend coverage includes real JWT access/refresh rotation, replay and version
revocation, CSRF, ownership, hidden private resources, lifecycle/configuration
locks, atomic ballots, historical reconciliation and results privacy. Additional
J tests verify middleware response headers, denied cross-origin credential
access and malformed JSON rejection without partial writes. PostgreSQL
concurrency classes cover authentication (5), legacy voting (5), lifecycle/share
races (7), and ballots/backfill (10).

The original four browser journeys remain, plus six guest/creator QA journeys
at 1280x900, 768x1024 and 390x844. Audited screens include Home, Explore, public
and private detail/results, login/register, recovery unavailable, not-found,
private access lost after refresh, My Polls, profile, creation validation,
management, confirmation and one-time sharing. Keyboard checks exercise the
skip link, confirmation focus/cancellation, native radio voting and mobile
menu Escape. Transport failure/retry uses an aborted real local request rather
than fabricated API responses. Reduced-motion removes the loading animation.
Axe checks tagged WCAG 2.2 AA rules and best practices, including color contrast.
Diagnostics export rule IDs/counts and static component names only, not form
values, tokens, DOM snapshots, traces or screenshots.

Persistent development startup was separately checked at localhost:5173 through
its same-origin API proxy. Read-only before/after counts across eight account
and voting tables were unchanged; no migration or account reset occurred.
See [Windows startup instructions](LOCAL_DEVELOPMENT.md).

## Manual checks still required

Automated passes are not WCAG certification. Before release, review NVDA/Firefox
and VoiceOver/Safari announcements, real-device touch, OS high-contrast mode,
browser zoom/reflow (in addition to tested CSS text scaling), text spacing and
long translated content. Safari and Firefox engines were not executed locally.
Review meaningful focus/reading order and error comprehension with human users.

## Remaining production gates / Milestone K priorities

1. Back up and restore-test production data; run restricted historical voting
   reconciliation and review anomalies before any approved backfill/ballot
   authority change. Bridge-mode tests do not constitute production cutover.
2. Validate trusted reverse-proxy HTTPS handling, redirects, secure cookies,
   explicit hosts/CORS/CSRF origins, static/frontend serving and rollback in a
   staging environment. Do not trust arbitrary forwarded-protocol headers.
3. Configure coordinated edge/shared-cache abuse controls and trusted client-IP
   handling for the actual deployment topology. DRF cache throttling is a
   best-effort budget, not a distributed hard request ceiling; shared/NAT peers
   can share its budget. Do not weaken origin rules or trust caller XFF values.
4. Resolve the existing tracked-history credential exposure with the owner:
   inventory access, rotate/revoke affected credentials explicitly, and review
   hosting integrations. No credentials were rotated and no history rewritten.
5. Password recovery remains disabled until trusted frontend origin and SMTP
   delivery/security policies are explicitly configured and tested. Local email
   stays in memory. No real reset email was sent.
6. Complete human accessibility and additional-engine review, and arrange
   frontend/integration CI and deployment review. The existing workflow runs
   backend tests/lint only; no deployment was introduced.

GitHub's published Milestone I run passed its Python 3.12 backend CI:
[run 41325268424](https://github.com/Tselot8/alx-project-nexus/actions/runs/41325268424).
Milestone J is local-only and has no new GitHub CI execution until an authorized
push. No production service or external hosting configuration was accessed.


Milestone K preparation and the single current release checklist are in
[RELEASE.md](RELEASE.md). The counts above remain the historical J verification;
K verification does not grant deployment, credential rotation or voting cutover.
