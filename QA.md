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


## Milestone L local staging-preparation verification (2026-11-06)

Baseline: clean chore/nexus-readiness at
853ab4f15b8e163f2f0fcce312cc4eafed322a28, matching the read-only remote
development hash. K contains the previously staged startup fix. L creates no
commit/push and does not change main or any cloud service.

### Final executed evidence

- Complete backend: **326 passed, 217 subtests passed**, no failures/skips,
  against owned tmpfs PostgreSQL 15. Includes prior model/migration,
  security/concurrency and new artifact/health/HTTPS-cookie regressions.
- Frontend: **271 passed**; npm ci, ESLint, strict app/E2E TypeScript and
  production build passed, with zero npm audit findings from that install.
- Integration: **16 passed**, no skips, including **10 real Chrome journeys**
  (four participant/creator/session journeys and six desktop/tablet/mobile
  accessibility/keyboard/reflow cases). Final run used FORCE_COLOR=1 and the
  shared HTTP probes, without banner detection.
- Django system check: no issues. makemigrations --check --dry-run: no changes.
  Full CI-equivalent Python lint plus gunicorn.conf.py lint passed.
- Offline production settings/deployment checks, temporary static collection
  and actual built-frontend routing passed with service connections blocked.
  Secure cookies, valid/missing/untrusted-origin CSRF and no-session 401
  exercised using production middleware. Real-JWT HTTPS session regression
  verifies rotation, stable CSRF, current user and logout on the test database.
- Docker BuildKit artifact built on Python 3.12/Node 22. Network-disabled,
  unpublished non-root Gunicorn smoke passed: SPA, assets, Django API/CSRF,
  database-independent liveness and expected unavailable-database 503 readiness.
  Private-looking malformed request content did not reach server logs.
  Only nonce-labelled owned containers/image were cleaned.
- Initial public dependency downloads timed out. Retried with bounded pip
  timeouts and BuildKit package cache, retaining TLS validation. A Windows
  subprocess decoding error was fixed by explicit UTF-8 replacement decoding;
  the final cached artifact check passed without that error. Raw registry/pip
  output is not printed/stored by verify_staging.py because errors can contain
  signed download URLs.
- Current working-tree secret scan: zero findings. Available-history scan:
  74 metadata findings (41 Compose credential-literal revisions, 30 old CI
  credential-literal revisions, three CI secret-printing revisions). Repeated
  revisions are not distinct credentials. Values were not included in reports;
  no credential was rotated or history rewritten.
- Git diff --check and cached --check passed. No models, migrations, poll voting
  services/ledger, frontend source, local Compose, .env.local or tracked static
  assets were modified. All 197 tracked static assets remain unchanged.
  No persistent local database was connected to or altered by L.

Existing drf-yasg renderer deprecation remains visible. Deployment checks retain
HSTS W005/W021, explicitly acknowledged only for the synthetic host-only
candidate; actual hosting/HSTS review is still mandatory.

### Not executed / still blocked

No cloud staging was created, deployed or tested. Provider signup/card-free
eligibility, real DNS/HTTPS/proxy/header behavior, remote PostgreSQL TLS/major
version/persistence, backup/restore proof, SMTP delivery, production voting
import/cutover and manual assistive-technology/additional-browser checks were
not performed. Recovery and production ballot writes remain disabled.

K GitHub run 42244485788 completed **failure**: backend/frontend passed, full-stack
failed; public logs returned 403. The new four-job workflow has not been pushed
or executed. A local readiness correction is not evidence that the remote
failure is resolved. Candidate CI success and owner log review remain gates.

[STAGING.md](STAGING.md) contains the provisional hosting comparison and manual
staging sequence. [RELEASE.md](RELEASE.md) remains the single go/no-go checklist.
**Preparation is ready for review; real staging/public launch is NO-GO until
mandatory approvals and release gates are satisfied.**


## Focused full-stack CI fixture correction (2026-11-08)

Baseline: clean chore/nexus-readiness at
92487ad920c922e3aa22d50f7b2a693bddb3ec67. The reported GitHub run
42408856608 had 4 integration passes and 12 setup errors at the bare bind
probe on 127.0.0.1:5181. No cloud action, commit or push is part of this fix.

The defect was reproduced with real Linux sockets: after a server was closed,
its accepted connection remained in /proc/net/tcp state 06 (TIME_WAIT). The old
bare-bind probe rejected that port even though its listener had been closed.
It failed both the TIME_WAIT regression and rapid repeated-restart checks.
The existing direct Node Popen handle was already waited for; fixed delays or
killing more processes would not correct this socket-state classification.

The runner and fixture now share a bind-and-listen probe using POSIX
SO_REUSEADDR, never SO_REUSEPORT. Windows uses SO_EXCLUSIVEADDRUSE without
enabling SO_REUSEADDR. Active conflicting listeners remain rejected.
full_stack remains function-scoped, preserving transactional DB cleanup,
cache clearing and fresh browser artifacts. Its managed_stack context is also
used directly by lifecycle regressions. Success and failed readiness reuse
the existing stop_owned helper: terminate/wait, then kill/wait only the exact
owned child on timeout. No unrelated process is located or terminated.

Final evidence:
- Four database-independent socket tests passed on Windows Python 3.10 and
  inside an owned, network-disabled Linux Python 3.12 container. They cover
  actual TIME_WAIT, live loopback/range-owner rejection and five rapid cycles.
  No tests were skipped. The Linux image/container were cleaned by nonce label.
- Four real Vite fixture regressions passed against disposable PostgreSQL:
  three consecutive managed-stack lifecycles, readiness-failure child reaping
  while an unrelated listener survives, and two per-test DB/cache isolation
  cases. Successful children exited, artifact directories disappeared and the
  port was reusable without a fixed sleep.
- The complete default python -B scripts/verify_fullstack.py command passed
  TWICE consecutively (exit 0 each), each with a fresh owned PostgreSQL container:
  330 backend tests / 222 subtests, 271 frontend tests and 20 integration checks,
  including 10 real Chrome journeys. No tests failed or were skipped.
- Both runs passed npm ci, ESLint, strict app/E2E TypeScript, production build,
  Django checks and makemigrations --check --dry-run. Colored output was enabled
  to retain coverage of banner-independent HTTP readiness.
- CI-equivalent Python lint, source secret scan (zero findings) and Git
  whitespace checks passed. Existing drf-yasg deprecation and explicit
  FORCE_COLOR/NO_COLOR notices remain visible.
- Both full runs removed only their owned disposable resources and verified
  the existing Docker container/volume/network inventories were preserved.
  No persistent local database or .env.local was read, copied or modified.
- Application authentication/voting, models, migrations, settings, URLs,
  frontend source, deployment configuration and tracked static assets were
  unchanged. Existing assertions remain intact.

GitHub Actions has NOT run this uncommitted correction. The old failed run is
not cleared by local results; a separately approved commit/push and successful
CI rerun are still needed before resuming the staging gate.


## Milestone M preparation checkpoint (2026-11-08)

Verified clean pre-M chore/nexus-readiness at
38d4d942330b64e3a40c286f2ca3d811c24773f5, matching the actual remote hash.
[GitHub run 42415505625](https://github.com/Tselot8/alx-project-nexus/actions/runs/42415505625)
passed all four jobs: PostgreSQL backend, frontend lint/tests/types/build,
full-stack/browser integration, and Docker production artifact.
The previous CI failures have been superseded for this candidate.

Local M checks:
- Enhanced verify_staging smoke passed with exact Docker limits:
  memory=512000000 bytes, swap allowance equal to memory (no extra swap),
  NanoCpus=100000000 (0.1 CPU), runtime PORT=10000, user=10001:10001 and
  OOMKilled=false. The network-disabled container served SPA, static/API/CSRF,
  liveness and expected unavailable-DB 503 readiness. The Debian CA bundle at
  /etc/ssl/certs/ca-certificates.crt loaded as the non-root user. This does not
  verify an external Neon certificate or real mixed-load capacity.
- Offline production configuration/deployment, built frontend/static/API routing
  and CSRF checks passed with database/network connections blocked.
- Focused production/security/isolation suite passed: 42 tests, 104 subtests,
  zero failures/skips, on a fresh owned tmpfs PostgreSQL instance. Django system
  checks passed and makemigrations --check --dry-run reported no changes.
- Full backend/frontend/integration suites were not repeated locally for this
  documentation/test-script change: the exact published candidate has green
  GitHub CI and the previous two complete local runs are recorded above.
- CI-equivalent lint, current-source secret scan and Git whitespace checks
  passed. HSTS W005/W021 remain visible/explicitly reviewed for the synthetic
  host-only check, and the existing drf-yasg renderer deprecation remains.
- Only owned temporary resources were removed. No persistent local DB,
  .env.local, credentials, models, migrations, API logic, frontend source,
  production settings or live cloud resource was modified/accessed by M.

STAGING.md now restricts the deployment to Render Free + Neon Free only and
specifies exact dashboard/secret/environment instructions with approval A-D
boundaries. RELEASE.md remains the single checklist. No code runtime fix was
required; verify_staging.py alone was strengthened for resource/port/CA checks.

No real staging URL exists or was tested. Account-specific no-card/$0
confirmation, assigned hostname, ingress header stripping, Neon TLS/role grants,
approved cloud migration/backup/restore/reconciliation, synthetic voting/restart
smoke and manual accessibility checks remain. Password recovery and production
voting defaults stay disabled. No commit, push, merge or deployment occurred.


## Local PostgreSQL 18 readiness/recovery rehearsal (2026-11-13)

Baseline chore/nexus-readiness at 38d4d942330b64e3a40c286f2ca3d811c24773f5.
The four existing M preparation modifications were preserved. No commit/push,
Neon connection, cloud SQL, Render resource or deployment was performed.

Environment: fresh task-owned temporary venv, Python 3.10.9 (no local 3.12 found),
Django 5.2.18, psycopg2-binary 2.9.11/libpq 16.9, pytest 9.0.1,
pytest-django 4.11.1; actual imports, pytest.fixture and distutils shim verified.
The older temporary environment was not repaired in place. Node 22.14.0/npm
10.9.2, local Linux Docker client/server 28.1.1. Artifact uses Python 3.12.

Executed results (zero final failures/skips):
- PostgreSQL 18.7: focused configuration/staging/settings 42 tests + 104 subtests;
  complete backend 334 tests + 229 subtests, including all 27 concurrency methods.
  The increase from 330 is four new full-stack image/storage guard regressions.
- Settings isolation unittest: 15 passed. Django system checks passed;
  makemigrations --check --dry-run reported no changes.
- Frontend npm run check: ESLint, strict application/E2E TypeScript, 271 unit tests
  and production build passed. The default full-stack run also completed a fresh
  npm ci/check in its temporary frontend copy.
- PostgreSQL 15.14 default full-stack: 334 backend + 229 subtests, 271 frontend,
  20 integration checks passed, including 10 real Chrome journeys.
- Explicit PostgreSQL 18.7 full-stack --postgres-major 18 --integration-only:
  all 20 real HTTP/browser/accessibility checks passed. This intentionally reused
  the already checked frontend and did not repeat the separate PG18 backend run.
- check_release.py with built frontend, audit_secrets.py (zero findings), complete
  CI-equivalent flake8 and Git whitespace checks passed.
- verify_staging.py passed actual non-root Gunicorn at 512 MB/no extra swap,
  0.1 CPU/PORT=10000: SPA/static/API/CSRF, HTTP 200 liveness, expected offline
  HTTP 503 readiness, CA loading and log-privacy canary. Owned artifacts cleaned.

PostgreSQL 18 migration/recovery evidence:
- Existing schema tests exercised fresh install, B1 upgrade preservation,
  reversibility, deferred cross-poll FKs and constraints on disposable test DBs.
- An additional fresh source applied all 40 migrations. Synthetic fixture:
  22 tables, 179 constraints (including PG18 NOT NULL), 83 indexes, two submitted
  ballots (native + imported) and one unchanged historical Vote source row.
- Container PG18.7 pg_dump custom archive, --no-owner/--no-acl; pg_restore --list
  inspected, SHA-256 matched container/archive copy. Restore into a separate
  new local target used --exit-on-error --single-transaction --no-owner --no-acl.
- Source/restored fingerprints matched every table row, IDs/timestamps, columns,
  migration history, index definitions and sequence state. Constraints were
  validated/enforced; all-poll reconciliation and read-only require-cutover-ready
  preflight passed on source and restored DB, with zero drift/quarantines/history
  gaps. No real/local developer or Neon data was backed up or copied.
- Initial recovery comparison found equivalent array/text cast formatting in
  three deparsed enum CHECKs. The task-only comparator now round-trips those
  definitions through the same PG18 parser on transaction-local tables; it also
  verifies actual invalid-value CHECK rejection. All other comparisons remain
  strict. No application constraint or existing test assertion was weakened.
- A separate new local DB rehearsed the documented grants: a non-superuser,
  non-CREATEDB/non-CREATEROLE migrator (not DB owner) applied all migrations;
  runtime had no role memberships/ownership/schema CREATE. Migration-history
  SELECT and an application sequence-backed insert worked (insert rolled back).
  Seven forbidden operations were rejected: schema CREATE, table ALTER, history
  INSERT/UPDATE/DELETE/TRUNCATE, and privilege alteration of another role.

Isolation/cleanup: only newly nonce-named local roles/databases and owned
container tmpfs stacks were removed. nexus-staging-test-db stayed running with
zero restarts and its original volume; unrelated resources were preserved.
.env.local and the four pre-existing changes were not discarded. Credentials
were generated/handled only in process memory, not SQL files or Git. Sanitized
verification logs and the one-off recovery harness are in the task-owned OS
temporary workspace; they are not an application/deployment entry point.

No polling/authentication/model/schema/settings/deployment behavior changed.
Existing drf-yasg deprecation and host-scoped HSTS W005/W021 remain visible.
Local PG18.7 success is not an independently verified Neon PG18.6 migration,
remote TLS/role guarantee, hosting proxy test or GitHub CI run for this diff.
