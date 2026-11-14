# Project Nexus release process and single go/no-go checklist

Status: **PREPARATION ONLY; NO PRODUCTION RELEASE AUTHORIZED.**
This file is the release checklist and operator runbook. QA.md records Milestone
J evidence. Passing local/CI tests does not satisfy the manual gates below.
No command in this document was executed against production during Milestone K.

## Baseline and retained work

Milestone K is 853ab4f15b8e163f2f0fcce312cc4eafed322a28 on
chore/nexus-readiness. At L inspection, local HEAD, upstream tracking and the
read-only GitHub branch hash matched K; working tree and staging were clean.
The startup-readiness correction is included in K (committed and published).
L preserves that history, leaves its own changes uncommitted, and never changes
main or its legacy deployed service.
Before a release, record the approved full commit, artifact hashes and actual
running application/migration versions. Do not assume production matches Git.

## Current Milestone M checkpoint (2026-11-08)

Published candidate: 38d4d942330b64e3a40c286f2ca3d811c24773f5.
Local branch/upstream/remote matched and the working tree was clean at inspection.
[CI run 42415505625](https://github.com/Tselot8/alx-project-nexus/actions/runs/42415505625)
completed success for all four jobs. The earlier failed runs below are historical.
M restricts hosting to Render Free Web Service plus Neon Free PostgreSQL only;
no fallback provider, card, paid plan/trial, credits or automatic upgrade.
[STAGING.md](STAGING.md) contains exact dashboard fields and explicit A-D gates.
No account, service, database, connection or deployment has been created by M.
Current local changes are documentation and an enhanced offline artifact check;
they are uncommitted and do not claim a new GitHub CI execution.

## Automated preparation gates

```powershell
# Existing Python environment must have the reviewed requirements installed.
python -B scripts/audit_secrets.py
python -B scripts/check_release.py
python -B scripts/verify_fullstack.py
python -B -m flake8 --extend-exclude "*/migrations/*" accounts polls alx_project_nexus manage.py scripts integration
git diff --check
```

check_release.py clears inherited application/database overrides, blocks network
and database access, disables dotenv loading, uses generated synthetic values,
and runs production Django deployment checks plus release_preflight. It collects
admin/DRF static assets only into a new temporary directory, then removes it.
It does not validate real hosting, SMTP delivery, credentials or production data.
The synthetic candidate explicitly acknowledges only security.W005/W021 because
HSTS remains host-scoped without preload. These warnings stay visible.

verify_fullstack.py uses ownership-labelled tmpfs PostgreSQL, fresh accounts and
polls, isolated settings and same-origin Django/Vite. It verifies migrations,
backend/concurrency tests, npm ci/lint/types/unit/build, real HTTP, Chrome and
axe desktop/tablet/mobile journeys. Existing development data is not used.
See integration/README.md for isolated reruns and cleanup safeguards.

K GitHub Actions has three test-only jobs: backend/configuration/secret checks,
frontend lint/tests/types/build, then disposable full-stack/browser checks.
Actions are pinned to verified full commit hashes and checkout credentials are
not persisted. There are no deploy steps, production migrations, repository
secrets or pull_request_target workflows. The changed workflow must pass on
GitHub's Python 3.12/Linux/Chrome runner after a separately approved push.
L adds a fourth test-only local Docker artifact job. No workflow deploys.
Configure required status checks/branch protection separately with owner approval.

Final local K verification used a separate Python 3.10.9 environment with the
reviewed Django 5.2.18 pin. The original developer venv was not upgraded.

- Final backend suite: **311 passed, 192 subtests passed**, including 27 existing
  PostgreSQL concurrency cases and the approved view-only admin HTTP tests.
- Frontend: **271 tests passed**; npm ci, ESLint, strict application/E2E TypeScript
  and production build passed.
- Full-stack: **16 integration checks passed**, containing **10 real Chrome
  journeys**, including desktop/tablet/mobile axe, keyboard and reflow checks.
- Offline production/deployment checks, temporary static collection, current
  source secret gate, complete Python lint and Git whitespace checks passed.
- Local --smoke passed on alternate ports 8001/5174; the ordinary port check
  refused 8000, and no existing process was stopped. Persistent database access
  was read-only; no credentials, records or volumes were changed.
- No mandatory local test was skipped. Existing drf-yasg renderer deprecation
  remains unsuppressed. HSTS W005/W021 remain visible and explicitly acknowledged
  only for the synthetic host-scoped candidate. Real HSTS policy needs review.
- Models, historical migrations, voting services, frontend sources, the dedicated
  local Compose file and all 197 tracked static assets remain unchanged.

## Production environment contract

Use .env.production.example as a sanitized inventory, not as working credentials.
Provide real values through the host's approved secret store/process environment.
The existing WSGI entry point remains alx_project_nexus.settings. Its historical
root .env loading remains for compatibility; never copy local dotenv files into
an artifact or rely on a public/tracked root .env. The local startup selects
settings_local explicitly and never reads production configuration.

Required production values: DJANGO_SECRET_KEY (random, >=50 characters with
varied characters), DJANGO_ALLOWED_HOSTS (explicit bare hosts), POSTGRES_DB,
POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_HOST, POSTGRES_PORT, DJANGO_PROXY_MODE.
Missing/invalid values stop settings import without printing their values.
The former provider-specific allowed-host fallback has been removed.

- Keep DEBUG false, HTTPS redirects on and session/CSRF/refresh cookies Secure.
  Refresh cookies remain HttpOnly, SameSite=Lax and Path=/api/v2/auth/. Access
  JWTs remain short-lived and memory-only; auth_version revokes legacy/v2 tokens.
- Prefer one HTTPS origin for the frontend and /api/ proxy. Keep production
  CORS_ALLOW_ALL_ORIGINS false and credential CORS disabled. Configure only
  reviewed HTTPS CORS/CSRF origins. Cross-site refresh-cookie architecture is
  not enabled by listing a CORS origin and requires a separate security decision.
- DJANGO_PROXY_MODE=direct ignores forwarded protocol. The backend must then
  receive TLS directly. DJANGO_PROXY_MODE=trusted enables only the standard
  X-Forwarded-Proto=https mapping and requires DJANGO_PROXY_HEADERS_STRIPPED=true.
  Set that acknowledgement only after verifying a controlled ingress strips
  client protocol headers, writes its own value, preserves the reviewed Host,
  and prevents direct untrusted access to the backend. Forwarded host/port
  trust remains disabled. Never fix a redirect loop by disabling HTTPS.
  See [Django proxy trust](https://docs.djangoproject.com/en/5.2/ref/settings/#secure-proxy-ssl-header).
- POSTGRES_SSLMODE defaults to verify-full. Supply the reviewed CA via
  POSTGRES_SSLROOTCERT/libpq trust configuration. Remote plaintext is rejected;
  disable is permitted only for loopback/socket connections. require/verify-ca
  are explicit compatibility choices, not proof of hostname verification: require
  a documented security exception before release. Test the actual certificate.
- DJANGO_HSTS_SECONDS defaults to zero so this preparation does not pin browsers.
  After HTTPS/redirect validation and approval, stage a small positive value.
  Preflight blocks security.W004 (zero HSTS). Subdomains/preload remain false:
  acknowledge W005/W021 individually only after documenting why broader HSTS
  is inappropriate. No arbitrary warning IDs can be waived by release_preflight.
- Local/test profiles retain isolated PostgreSQL, caches, HTTP cookies and local
  email capture. No production environment flag may weaken those boundaries.
- Review coordinated ingress/shared-cache rate limits and peer-IP handling.
  Existing DRF budgets use actual REMOTE_ADDR, not caller XFF; locmem throttles
  are best-effort and per-process, not distributed abuse protection.

After explicitly loading the approved production environment in a management
process, configuration-only checks require no database connection:

```powershell
python -B manage.py check --deploy --fail-level WARNING
# If host-only HSTS is the approved policy, review those warnings and use:
python -B manage.py release_preflight --production --acknowledge-warning security.W005 --acknowledge-warning security.W021
```

The first command intentionally exits nonzero for unacknowledged warnings.
Do not blindly acknowledge warnings or treat deployment_authorized=false in the
JSON as deployment permission. No code can verify ingress isolation for you.

Admin poll/option/audit models are now view-only, including for superusers.
Inline mutation and bulk actions are disabled; owner workflows still use the
transactional API. Account/category administration remains available and legacy
Vote evidence remains immutable. Deploying older writable admin code alongside
this release would reintroduce a bypass; inventory admin instances too.

## Credential exposure and rotation gate

The available Git history contains database-password literals in
Docker Compose and older CI workflows, plus secret-printing commands in old CI.
Current Compose now requires environment substitution; historical copies remain.
The legacy root Compose file is not a production deployment plan: it retains
legacy host port mappings and an unused optional broker. Do not run it on a
public production host; the separate local Compose setup remains unchanged.
The history audit reports path/revision/line/class only; repeated revisions are
not distinct credentials. It is a heuristic, not a guarantee that every secret
has been detected. No secret value is included in this report.

```powershell
# Read-only local Git audit; a nonzero status means findings remain.
python -B scripts/audit_secrets.py --history
```

Treat exposed database credentials as compromised until the owner proves they
were test-only or rotates them. Review Django signing secrets potentially
exposed through CI logging, and any deployment hooks/SMTP credentials present in
those restricted logs. Do not paste values or logs into tickets/chat. The current
working-tree gate does not clear historical exposure or invalidate issued tokens.

Operator-only rotation procedure: inventory affected environments/consumers;
back up configuration in restricted storage; approve a maintenance/rotation plan;
issue replacement credentials with least privilege; update the approved secret
store; restart consumers/pools; verify new access and rejection of old access;
revoke old credentials and review audit logs. Signing-key rotation invalidates
JWTs and may invalidate reset/session signatures. Do not add a compromised key
as a fallback. Plan user reauthentication and verify revocation. Review any key
fallback overlap explicitly rather than retaining compromised credentials.
Review GitHub logs/artifacts/forks and access; history rewriting is a separate
owner-approved operation and never substitutes for revocation. K rotates nothing.

The Django pin is upgraded from 5.2.8 to the 5.2.18 security patch in the same LTS
line. See [5.2.18 security notes](https://docs.djangoproject.com/en/5.2/releases/5.2.18/)
and the [5.2.9 high-severity advisory](https://www.djangoproject.com/weblog/2025/dec/02/security-releases/).
No claim is made that the application exposed every affected feature. Verify
remaining Python/npm advisories at release time; pinned versions are not an
ongoing vulnerability feed. Deploy the patched requirements, not an old venv.

## Password recovery and SMTP gate

Recovery remains disabled unless NEXUS_PASSWORD_RESET_ENABLED=true AND
NEXUS_PASSWORD_RESET_APPROVED=true in production. Approval is an operator
attestation, not an automated feature enablement. Require one HTTPS trusted
NEXUS_PASSWORD_RESET_FRONTEND_ORIGIN, a valid sender, SMTP host and either both
auth credentials or an explicitly approved anonymous relay. Security must be
starttls or ssl; configure port and bounded timeout (default 10s, maximum 60s).
Console/file email backends are not enabled in production. Isolated settings
always capture email in memory. See [Django SMTP settings](https://docs.djangoproject.com/en/5.2/topics/email/#smtp-backend).

The reset flow already uses expiring, single-purpose, single-use tokens, generic
202 responses and auth_version revocation after reset. SMTP failures retain the
generic response without logging message bodies/tokens or mutating passwords.
Delivery is synchronous: review timing-enumeration and failure-monitoring policy
before approval; a generic body is not a timing guarantee. Operator-controlled
SMTP tests must use synthetic recipients and inspect TLS, SPF/DKIM/DMARC,
bounce/delivery behavior and frontend fragment handling without collecting raw
reset links. No real email is sent by K. Disabling recovery remains acceptable
for a release if clearly communicated; it is not ready to enable by default.

## Backup, restore and migration gate (operator approval required)

All commands below that use the real database require separate approval. K runs
only disposable tests. Confirm the destination by database identity and network
allowlist before connecting, including read-only preflight. Use a least-privilege
read-only role for inspection and a separate restricted migration/import role.
Keep credentials outside arguments, shell history and repository files; use an
approved secret injector or protected PGPASSFILE.

1. Inventory deployed SHA, database/server version, migration history, data size,
   active legacy writers/jobs/admin paths and backups. Record aggregate baseline
   counts privately, never individual voting records in routine reports.
2. Take a consistent custom-format pg_dump to restricted storage. Example only,
   after PGHOST/PGPORT/PGUSER/PGDATABASE are loaded securely:
   `pg_dump --format=custom --no-owner --no-acl --file $backupFile`.
   Verify exit status, checksum, encrypted storage/access and retention.
3. Restore into a separately approved NEW empty disposable database, never the
   source: `pg_restore --exit-on-error --single-transaction --no-owner --no-acl --dbname $restoreDatabase $backupFile`.
   Confirm target identity first. Validate constraints, migration state, counts,
   application reads and restore duration. Record proof and RPO/RTO; no --clean,
   source overwrite or automatic restore is authorized by this document.
4. On the disposable copy inspect showmigrations --plan, migrate --plan,
   makemigrations --check --dry-run and relevant sqlmigrate output. Apply the
   exact candidate migrations there and run tests/reconciliation. Polls 0006
   creates a concurrent index and must remain non-atomic. 0007 attaches indexes
   and adds constraints with strong locks; 0008 validates them. Inspect invalid
   concurrent indexes rather than silently replacing them. This is not a
   zero-downtime guarantee; use reviewed lock/time budgets and a maintenance plan.
5. After backup/restore proof and explicit production migration approval, run
   migrations as a one-off managed operation with writers drained as required.
   Build/start commands and CI must never run production migrate automatically.
   Do not fake migration history, reverse populated ballot tables, or assume
   dropping additive tables is a rollback after participation has started.

## Voting bridge, reconciliation and cutover (separate approvals)

Existing /api/ and /api/v2/ voting use the same parent-Poll-locked ballot writer.
Vote is immutable historical evidence. Bridge results combine disjoint historical
and ballot cohorts; ballot-only results require complete reconciliation. Never
sum Vote and BallotSelection indiscriminately or enable an old independent
Vote writer. Imported ballots preserve the earliest surviving source timestamp,
not evidence of already-deleted history. Counters are derived compatibility data.

A. **Read-only preflight approval.** Keep service flags bridge/false until all
pre-F API/worker/admin writers are stopped and verified drained. Run:

```powershell
python -B manage.py release_preflight --database
```

This uses READ ONLY, REPEATABLE READ, 5s lock and 30s statement timeouts. It checks
migration state, named validated integrity constraints, aggregate counts,
unconverted groups, quarantines and counter drift. It never FOR UPDATE locks,
imports or repairs rows. Plan large scans: a long snapshot retains MVCC history.
Its output contains no poll/user/selection identifiers. Counter drift must be
explained and approved; this command never repairs it. A clean point-in-time
report is not a fence against later writers.

B. **Bounded dry-run approval.** With source Vote groups frozen, run
`python manage.py backfill_ballots --dry-run --limit 100 --offset 0`.
Follow next_offset until more=false. Unlike the new preflight, this existing
command DOES acquire parent Poll row locks even in dry-run/reconcile mode.
Do not run it with a read-only role or call it lock-free. Reports are counts only.
Unexplained anomalies block cutover; do not choose/discard selections or rewrite
Vote rows to make reports green.

C. **Import approval.** Keep web/worker voting paused. In a separately approved
management-only process set authority=bridge and writes_enabled=true (the existing
import guard requires it); this does not authorize enabling web-service writes.
Run `python manage.py backfill_ballots --apply --confirm-frozen-writers --limit 100 --offset 0`.
Advance stable offsets from the reports. Imports commit per group and can leave
successful groups if a later group quarantines. Source IDs/timestamps remain;
repeating batches is idempotent. On failure, stop, preserve evidence and review
privately; never reset tables or rerun destructive migrations.

D. **Reconciliation approval.** Still with all service writers paused, run
`python manage.py backfill_ballots --reconcile` without --poll. Require a zero
exit, scope=all, ready=true and no quarantines. Also run:

```powershell
python -B manage.py release_preflight --database --require-cutover-ready
```

Require all source cohorts converted and no unresolved discrepancies. Record the
candidate SHA, time, source freeze and report hashes privately. Do not treat a
single-poll reconciliation as whole-system readiness.

E. **Cutover approval.** Only after D, set service authority=ballots while voting
stays paused; restart all compatible instances, repeat read-only evidence and
privacy/result smoke checks. Obtain separate approval to enable web-service
ballot writes, then verify complete replacements, counts and legacy adaptation
with an approved synthetic scenario. Never perform backfill/cutover at startup,
in schema migrations, CI or ordinary deployment scripts.

**Rollback:** first pause voting, retain both stores/audit evidence and snapshot
the incident state. Roll back application code only to a schema-compatible,
patched F-or-later artifact. Bridge mode can be restored by approved operator
configuration without deleting ballots; do not return to a Vote-only writer.
Do not decrement auth_version or restore an old database snapshot over newer
votes. Database restore/data repair is an exceptional, separately approved
recovery decision with an explicit data-loss/RPO assessment. Prefer roll-forward.

## Build, deployment, health and monitoring (operator-only)

Build immutable artifacts from the approved SHA: install pinned Python packages,
run npm ci and npm run check, and package frontend/dist with matching backend.
Collect Django admin/DRF static assets in a build/staging artifact directory,
not the developer checkout. Under DEBUG=false, Django runserver does not serve
production static assets. Configure a reviewed web server/object-store mapping
for /static/, plus SPA fallback for frontend routes only. /api/ and /admin/ must
reach Django; API errors must never become frontend HTML. Use a production WSGI
server (for example the existing Gunicorn dependency), not runserver or Vite dev/
preview. Same-origin proxying is the baseline; no provider is assumed.

Before any approved push/merge, reverify hosting auto-deploy branches/hooks and
branch protection. Render was previously main-only, but this milestone makes no
live hosting assertions. Stage the same artifact/environment first. Review HTTP
redirects, TLS/proxy trust, hosts/origins, cookies, static content, SPA navigation,
CSP/security headers, database privileges and monitoring. Liveness can GET
/api/v2/auth/csrf/ without authenticating or writing data; validate JSON shape,
not HTTP 200 alone. L adds /health/live/ (no database) and /health/ready/ (bounded read-only
database connectivity and migration-plan checks). Neither is migration/cutover approval. The
comprehensive release_preflight remains separately approved operator evidence.
See STAGING.md for the combined Gunicorn/WhiteNoise artifact and HTTPS routing.

After an approved deployment, read-only smoke checks include /, /polls, /login,
admin static CSS, unknown/private resource 404, and no-store response headers.
Any live registration/vote/lifecycle/email smoke requires its own synthetic-data
approval. Monitor status/latency, 401/403/429/5xx, database locks/connection pools,
SMTP outcome metrics and reconciliation status. Never log Authorization, Cookie,
X-Poll-Share, reset/share/login request bodies, raw tokens or voter selections.
No analytics/error snapshots may collect private-link fragments or form secrets.
Record rollback owner, artifact, triggers and communication plan before go-live.

## Single release readiness checklist

Completed boxes are automated/local evidence only; manual boxes require a named
operator, date and evidence location. A local pass never authorizes deployment.

| Gate | State | Required evidence / go-no-go rule |
| --- | --- | --- |
| Git baseline / startup fix publication status | VERIFIED M | Published candidate 38d4d94 includes L and the port-reuse fix; clean pre-M baseline. |
| Synthetic production settings, host/proxy/SMTP guards | PASS local | Offline checks and focused regressions; no live credentials. |
| Current-source secret gate | PASS local | Zero current literal/sensitive-file findings; history remains separate. |
| Backend, frontend, full-stack and concurrency suites | PASS local L | 326 backend / 217 subtests, 271 frontend, 16 integration incl. 10 Chrome journeys; no failures/skips. |
| Static collection / migration consistency | PASS local | Temporary admin/DRF assets verified; no new schema migrations. |
| Admin invariant bypass | PASS local | Poll/Option/AuditLog view-only, including superusers, inline and bulk requests. |
| GitHub Actions on Python 3.12 / Linux | PASS candidate 38d4d94 | Run 42415505625: backend, frontend, full-stack and Docker artifact all succeeded. Later changes require their own reviewed CI. |
| Hosting / no-card eligibility | MANUAL CHECK | Render Free + Neon Free ONLY, currently advertised card-free/non-trial; confirm actual $0 forms/account before approved creation. |
| Combined artifact / health / CSRF / static | PASS local M | Non-root at 512 MB, no extra swap, 0.1 CPU and PORT=10000; offline routing/CSRF/CA checks. No live staging or workload proof. |
| Staging persistence / quotas / cold-start | MANUAL BLOCKER | Approved NEW DB/service, synthetic record survival after restart, limits accepted. |
| Historical credentials / log exposure | MANUAL BLOCKER | Owner confirms test-only status or completes/retests required revocations. |
| Dependency advisory / patched runtime | MANUAL BLOCKER | Deploy reviewed patched requirements; audit remaining dependencies at release time. |
| Backup and disposable restore rehearsal | MANUAL BLOCKER | Approved target, verified restore, RPO/RTO and rollback artifact. |
| Real environment, TLS/proxy/origins/static/ingress abuse controls | MANUAL BLOCKER | Staging evidence, HSTS warning decisions and least privilege. |
| Voting writer freeze, import and all-poll reconciliation | MANUAL BLOCKER | Separate A-E approvals and reports; no automatic cutover. |
| Recovery SMTP activation | DISABLED | Keep disabled, or complete separate origin/delivery/security approval. |
| Human accessibility and other browser engines | MANUAL BLOCKER | NVDA/Firefox, VoiceOver/Safari, real mobile, high contrast, zoom/text spacing. |
| Hosting triggers / release sign-off | MANUAL BLOCKER | Reverified hooks/branches, owner approval and approved immutable SHA. |

**GO for release review** requires passing local automated gates with remaining
manual blockers clearly recorded. **GO for production** requires all mandatory
manual gates cleared, an explicit choice to keep recovery disabled or approve
it, and separate approval for migrations, cutover and deployment. Any unknown
credential state, unconverted/anomalous history, unsafe ingress or missing
restore proof is NO-GO. K itself performs none of those operator actions.


## Milestone L staging preparation

[STAGING.md](STAGING.md) records current hosting research, the provisional
same-origin architecture/fallback, sanitized environment contract and approval
sequence. Existing production security, historical-secret rotation, backup,
migration, reconciliation, accessibility and operator gates above still apply.

K GitHub run 42244485788 concluded failure: backend/frontend succeeded,
full-stack failed at Verify isolated full stack. Public annotations had no
details and job-log API required authorization (403). L does not assert a root
cause. The integration fixture independently had fragile exact-banner readiness;
it now reuses the verified HTTP probes. A future approved CI run must prove the
candidate on Linux/Python 3.12. Do not bypass a failed job or push from L.

Provisional staging remains NO-GO until candidate CI and manual hosting/security/
data gates are cleared. New staging voting writes need their own approval even
on a fresh database. Production writes/cutover remain untouched. Password
recovery stays disabled; Render Free blocks standard SMTP ports.

~~~powershell
# Local network-isolated artifact verification, not cloud deployment.
python -B scripts/verify_staging.py
~~~

This adds no migration or seed step to build/start. Database backups/restore and
reconciliation procedures above remain mandatory, separate operator actions.


## Milestone M approval sequence

The historical L no-go was resolved only for candidate CI. All real environment,
credential, backup/restore, DB identity/migration, role, proxy and write gates
remain. Approval A in STAGING.md permits a new Free Neon project/database only.
Approval B separately permits identified staging connections/migrations/grants/
restore testing; Approval C covers Render account connection, Free service
creation AND initial deployment. Approval D covers synthetic staging writes,
voting activation and restart/persistence smoke. No step implies the next one.

Use DB-independent /health/live/ for the Render platform check to avoid ongoing
Neon wake-ups; manually verify /health/ready/ after approved migrations.
Render can count a 3xx as healthy, so external verification must require actual
HTTPS 200 JSON without redirects. Never weaken HTTPS or proxy attestation.

Management owner credentials must not be mistaken for a restricted runtime role:
Neon console-created roles are elevated. Review grants before public service
deployment. No hardcoded actual hostname is added: populate exact allowed Host/
HTTPS origin only after it is assigned, and attest proxy stripping only on
provider evidence/verification. No wildcard or fake-domain fallback.

This checkpoint is GO for reviewing manual Free account/project setup only.
It is NO-GO for unapproved deployment, migration, voting or public launch.


## Local PG18 rehearsal checkpoint (2026-11-13)

QA.md records fresh local evidence: backend 334 + 229 subtests on PG18.7,
27 concurrency methods, frontend 271, full default PG15 gate and 20 live
integration checks on each PG15/PG18, production artifact smoke, migration
upgrade/reversal tests, synthetic dump/restore and restricted-role rehearsal.
The full-stack runner retains PG15 as default and adds explicit --postgres-major
18 with version-correct tmpfs storage and unchanged ownership/isolation gates.

Local migration/recovery prerequisites PASS. Existing Neon migrator/runtime
provisioning is owner-confirmed; do not rerun their CREATE/RESET instructions.
No Neon connection, migration or deployment was performed. Before actual cloud
migration, obtain explicit approval for a fresh bounded Neon identity/schema/
version/TLS preflight and protected baseline backup, review the rehearsed plan,
and retain a separate migration execution approval. Actual Neon is reported
18.6; this local rehearsal used 18.7. Do not infer live state from local success.

After future migrations, apply the explicit application DML allowlist as
migrator, keep django_migrations SELECT-only for runtime, and verify actual web
role/health behavior. Recovery remains disabled and voting remains bridge/false.
Hosting proxy/HTTPS/origins, historical credential sign-off, cloud backup/
recovery evidence, persistence/cold starts, human accessibility and reviewed
candidate CI/publication remain release gates. No push/commit is authorized.
