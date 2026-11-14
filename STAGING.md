# Project Nexus: Render Free + Neon Free staging guide

**Current checkpoint: Neon resources owner-reported created; restricted-role setup authorized for manual execution. Migrations/deployment NOT approved.**
Use the final "Neon role setup: authorized owner-operated workflow" section for
the current next steps; its authorization update supersedes the earlier A gate.
Reviewed 2026-11-08. This guide replaces the earlier provisional hosting choices:
only Render Free Web Service and Neon Free PostgreSQL are in scope. No fallback
provider, paid instance, trial, payment card, credits, add-on or auto-upgrade is
authorized. Keep the legacy main service and its database unchanged.

## Verified candidate and financial limits

Candidate: 38d4d942330b64e3a40c286f2ca3d811c24773f5 on chore/nexus-readiness.
Local/upstream/remote hashes matched, with a clean tree before M preparation.
[GitHub run 42415505625](https://github.com/Tselot8/alx-project-nexus/actions/runs/42415505625)
passed all four jobs: backend, frontend, full-stack and Docker artifact.
Earlier failed K/L runs remain historical evidence, not current blockers.
Any later candidate needs its own reviewed publication and green CI.

Official policies currently advertise these non-trial Free plans, not guaranteed
lifetime terms. Recheck the actual account/creation form before final submission:
- Render: Hobby workspace $0 AND Free service $0; 512 MB/0.1 CPU, idle sleep
  after 15 minutes and roughly one-minute cold start. 750 instance-hours are
  shared across the workspace, including the existing legacy service.
- Neon: Free $0, no time limit/no card advertised; 1 GB/project,
  100 CU-hours/project/month, 5 GB transfer/project; compute idles after 5 minutes.
- On quota exhaustion, accept suspension/restricted access; never upgrade.
  Storage still needs independent backups. No uptime guarantee is asserted.
- Render Free has no shell/one-off jobs or persistent disk. No paid cron/jobs.
  Use a separately approved management process for migrations.
- Keep both accounts without payment methods or paid/trial plans. If the actual
  flow demands a card, verification charge, subscription or paid feature, STOP.
  Do not remove/change billing on someone else's existing workspace.
- Do not enable AI credits, optional managed auth/functions or paid monitoring.
  Stop on an unexpected upgrade prompt. Review usage dashboards before launch.

Sources checked live:
[Render free limits](https://render.com/docs/free),
[Render no-card statement](https://render.com/articles/platforms-with-a-real-free-tier-for-developers-in-2026),
[Render instance sizes](https://render.com/docs/compute-plans),
[Neon pricing](https://neon.com/pricing),
[Neon quota behavior](https://github.com/neondatabase/website/blob/main/content/faqs/free-plan-limits-and-quotas.md).

## Local artifact contract

Dockerfile.staging uses BuildKit/Node 22 to build frontend/dist and Python 3.12
for DRF/Gunicorn/WhiteNoise. It collects static assets offline, starts as
10001:10001, and runs one Gunicorn worker with two threads. PORT is read from the
runtime environment; 0.0.0.0:10000 is compatible with Render's default.
Keep the Docker CMD; no build/start migration, token issuance, seed or backfill.

One HTTPS origin serves the application:
- / and React deep links: the built index, private/no-store and no-referrer.
- /assets/: public Vite assets only; /static/: collected Django/DRF assets.
- /api/, /admin/, /swagger/, /redoc/: Django, with no SPA fallback for errors.
- No production Vite server, separate frontend domain, permissive CORS or browser
  token storage is needed. Refresh cookies remain Secure/HttpOnly/Lax, auth-only
  path; access tokens remain memory-only.
- .dockerignore excludes dotenv, Git history, data, dumps and dependencies.
  Never declare secret ARG values in Dockerfile; Render supplies environment
  values to the build system too. No real secrets are needed for the build.

The M local smoke explicitly tests 512000000 bytes memory, no extra swap,
0.1 CPU and PORT=10000, non-root startup, static/API/SPA routing and a loadable
Debian CA store. It is a lightweight smoke, not a workload/cold-start benchmark
or an actual Neon connection. Stop if real staging exceeds Free limits.

[Render Docker configuration](https://render.com/docs/docker)

## Approval A: Neon account and fresh resources

**Instructions for review; do not click Create project/database until approved.**
No provider API/CLI login or cloud credential access has been performed.

1. Open https://console.neon.tech. Sign in, or use Sign up with your own account.
   Verify Free/$0 in the organization billing page. Decline trials and optional
   paid services. No card or prepaid balance.
2. Select New Project. Name: project-nexus-staging. Choose a region matching the
   proposed Render region where possible (Frankfurt is a candidate, not a paid
   requirement). Under Services, leave only Postgres enabled; expand its version
   selector. The existing staging project is owner-reported PostgreSQL 18.6;
   retain PostgreSQL 18. Do not recreate/downgrade it to match local/CI PostgreSQL
   15. PostgreSQL 18 live validation and migration rehearsal remain separate gates.
   If the selected region is unavailable on Free, stop rather than upgrading.
3. Review plan/cost again, then, ONLY under Approval A, click Create project.
   Use a NEW project: do not branch/copy an existing database. An initial branch
   labelled production/main inside this new project does not refer to Git main.
4. On that new project's branch, Postgres database > Databases > Add database.
   Name: nexus_staging. Select that new project's generated owner, then Create
   only under Approval A. Do not delete the automatically created neondb.
5. Skip sample SQL, data imports and managed-auth tutorials. The staging database
   must have no Nexus user/poll/vote data. Never upload a local backup.
6. Open Connect. Choose the NEW branch, nexus_staging and its intended role.
   Turn Connection pooling OFF for the direct endpoint (no -pooler hostname).
   Keep host, database, role and password private in your provider dashboards/
   approved credential manager; never paste the URL/password into chat or logs.
7. Return only the non-secret project name, region, PostgreSQL major version and
   confirmation Free/$0/no card. Resource approval is not connection/migration
   approval. Do not run psql, SQL Editor commands or Django migrate yet.

Console-created roles are elevated Neon roles, even if named nexus_runtime.
The initial generated owner is a management identity, not proof of least
privilege. Before web deployment, review a separate SQL-created restricted
runtime role and grants under Approval B. This costs no paid plan but is a
cloud database change. Avoid plaintext passwords in SQL Editor/history.

[Project form](https://neon.com/docs/manage/projects),
[Database form](https://neon.com/docs/manage/databases),
[Role privileges](https://neon.com/docs/manage/roles).

## Approval B: staging identity, backup, migrations and grants

Require explicit approval to CONNECT to the identified new staging database,
inspect it, take/restore backups and execute DDL. These are not performed by M
preparation. Do not connect any production/local database.

Use the reviewed candidate image or pinned local management environment;
prefer the image's Linux CA bundle. Inject credentials in process memory,
not CLI values, source files, root .env or .env.local. Use an approved protected
PGPASSFILE/secret injector for pg_dump/restore; remove temporary credentials
securely after use. Never collect raw Docker inspect environment or DSNs.

Neon TLS: POSTGRES_SSLMODE=verify-full and
POSTGRES_SSLROOTCERT=/etc/ssl/certs/ca-certificates.crt inside this Debian image.
Use the direct DNS hostname, not its IP, for hostname verification. Keep
CONN_MAX_AGE=0; the small worker pool needs few connections. Do not add PgBouncer
or change to a transaction pooler without reviewing locking/migration behavior.
Windows psycopg cannot assume a file-based OS root store; use an approved CA file
or the Linux image instead. Do not weaken TLS to require/disable on failure.
[Neon TLS instructions](https://neon.com/docs/connect/connect-securely)

Approved management sequence (template only, not runnable credentials):
1. Verify database/server/role identity and that this is the NEW staging target.
   Record only aggregate counts; prove no source/local records were copied.
2. Follow RELEASE.md's custom-format backup/checksum/encrypted-retention and
   restore procedure. Restore only into an approved NEW disposable database.
   No --clean, source overwrite or drop/reset. An empty baseline is still useful
   identity/restore evidence; repeat backups after migrations and demo activity.
3. Run configuration preflight; then showmigrations --plan and migrate --plan.
   Inspect/rehearse polls 0006 concurrent index, 0007 locks and 0008 validation.
   Use reviewed lock/time budgets; do not assume zero downtime.
4. After the explicit migration approval, a ONE-OFF management process runs
   python -B manage.py migrate --noinput. Never insert it into Docker CMD,
   CI, Render build, pre-deploy or startup. Free shell absence is not a bypass.
5. With voting writes paused, run:
   python -B manage.py release_preflight --database --require-cutover-ready
   Review named validated constraints, counts, drift, quarantine and zero
   unconverted history. Run backfill_ballots --reconcile over all polls only
   with approval for its Poll row locks; it does not import data.
6. A truly fresh staging DB needs no historical backfill. Unexpected Vote rows,
   unknown history or anomalies mean STOP, not repair/drop. Keep authority bridge
   and writes false. Ballot-only authority and write enablement need Approval D.
7. Review/create a least-privilege runtime role with approved grants on the
   required app tables/sequences, plus SELECT on django_migrations for readiness.
   No schema CREATE/ALTER or migration-history write permission for the web role.
   Grant/password provisioning is a separate reviewed operation, not a secret SQL
   snippet pasted into a dashboard history. Keep the owner out of the web service.
8. Retest reads and permission denial with the runtime role, then record applied
   migration state and a post-migration backup. No public traffic yet.

Management-only checks that do not serve HTTP may use localhost as allowed Host
and direct proxy mode, with a separate temporary signing secret. Final web
configuration must use the actual assigned staging hostname and approved proxy.
Do not carry any temporary management settings into the web service.

## Approval C: Render connection, service creation AND initial deploy

**The final creation button also deploys. Approval A/B does not authorize it.**

1. Open https://dashboard.render.com. Use a Hobby $0 workspace with no payment
   method/paid subscription/trial. Confirm existing Free service hours do not
   exhaust the shared allowance. Do not edit the legacy alx-project-nexus service.
2. New + > Web Service > Git Provider > GitHub. If connecting the Render GitHub
   app is necessary, grant access only to Tselot8/alx-project-nexus. Repository
   connection is an external account change covered by Approval C.
3. Choose this repo and branch chore/nexus-readiness (NEVER main).
4. Name: project-nexus-staging, or a distinct available staging name. Region:
   match Neon where possible. Language/runtime: Docker. Instance: Free $0.
5. Root Directory: blank (repository root). Dockerfile Path: ./Dockerfile.staging.
   Docker Build Context: . if shown. Do not set a native Build Command: Dockerfile
   already builds React and collects static. Docker Command/Start override: blank
   to retain gunicorn -c gunicorn.conf.py alx_project_nexus.wsgi:application.
   Pre-deploy command: blank. No migration, disk, cron, broker or other service.
6. Advanced > Auto-Deploy: Off. Do not create deploy hooks/PR previews. Configure
   Health Check Path as /health/live/. It is DB-independent, avoids continual DB
   wake-ups, and does not claim migration or voting readiness. Check
   /health/ready/ manually after approved migrations; excessive DB monitoring can
   consume Neon allowance. Do not add external keep-alive pings to defeat sleep.
7. Obtain/confirm the exact assigned onrender.com hostname. Set the table below.
   Never guess a wildcard or use a suffix allowlist. If the form reveals the URL
   only after creation, STOP: creation already attempts deployment. Obtain
   approval for that initial attempt and configure the exact Host before a
   subsequent explicit redeploy; missing settings fail closed. No insecure
   placeholder/silent fallback is added.
8. Resolve the proxy trust gate before setting its attestation true. Render
   documents edge TLS with HTTP to the container and X-Forwarded-Proto. Also
   require evidence that client protocol headers are overwritten/stripped and
   untrusted callers cannot bypass the ingress. Documentation reviewed so far
   does not independently prove every stripping behavior. Get provider evidence/
   owner verification, then approve trust; do not blindly check the flag.
9. Review all cost fields, environment, candidate SHA and pending approval gates.
   Do not press Deploy Web Service/Create Web Service until Approval C includes
   resource creation AND initial deployment. Creating automatically starts it.
   If main/paid/card/trial appears, stop rather than continuing.
10. Confirm Auto-Deploy Off in Settings after creation. For subsequent deployment:
    Manual Deploy > Deploy a specific commit > reviewed green SHA > Deploy Commit,
    only with explicit deploy approval. Do not choose an unreviewed latest SHA.
    Check the actual staging URL and leave production main untouched.

Render health accepts 3xx too: a green dashboard alone cannot prove absence of
redirect loops. External HTTPS smoke must require 200 JSON on both health paths.
[Docker fields](https://render.com/docs/docker),
[Manual deploy/Off](https://render.com/docs/deploys),
[Health checks](https://render.com/docs/health-checks),
[Edge protocol](https://render.com/tutorials/web-service-vs-static-site/web-services).

## Render environment inventory (no real values in this document)

Enter values individually under Environment; do not import .env.local.
No real hostname exists yet. Replace HOST with the exact assigned bare hostname
only after approval; it is not a literal configuration value.

| Name | Value / handling |
| --- | --- |
| DJANGO_SETTINGS_MODULE | alx_project_nexus.settings |
| DJANGO_SECRET_KEY | New random 64-byte URL-safe secret; private value only |
| DJANGO_ALLOWED_HOSTS | HOST (bare hostname, no scheme/slash/wildcard) |
| DJANGO_CSRF_TRUSTED_ORIGINS | https://HOST (exact origin, no trailing path) |
| DJANGO_CORS_ALLOWED_ORIGINS | Leave unset/empty for this same-origin app |
| DJANGO_PROXY_MODE | trusted only after proxy approval |
| DJANGO_PROXY_HEADERS_STRIPPED | true only after the evidence/attestation above |
| DJANGO_HSTS_SECONDS | 3600 only after HTTPS review/approval; template starts at 0 |
| NEXUS_SERVE_FRONTEND | true (the generic example file's false is not this web configuration) |
| POSTGRES_HOST | Direct Neon endpoint hostname, no scheme or -pooler |
| POSTGRES_PORT | 5432 |
| POSTGRES_DB | nexus_staging |
| POSTGRES_USER | Approved restricted runtime role |
| POSTGRES_PASSWORD | That role's generated private password |
| POSTGRES_SSLMODE | verify-full |
| POSTGRES_SSLROOTCERT | /etc/ssl/certs/ca-certificates.crt |
| NEXUS_BALLOT_AUTHORITY | bridge |
| NEXUS_BALLOT_WRITES_ENABLED | false |
| NEXUS_PASSWORD_RESET_ENABLED | false |
| NEXUS_PASSWORD_RESET_APPROVED | false |
| PORT | Render supplies 10000; leave provider value unless separately reviewed |

Leave NEXUS_PASSWORD_RESET_FRONTEND_ORIGIN and all NEXUS_EMAIL_* sender/SMTP
fields unset. Do not enable recovery or Neon-managed authentication.
Do not set DEBUG, CORS wildcards, insecure cookies, USE_X_FORWARDED_HOST or
GUNICORN_CMD_ARGS to bypass the reviewed configuration. Do not set DATABASE_URL:
this app intentionally reads the separate POSTGRES_* fields.
NEXUS_FRONTEND_DIST may remain unset; the image includes /app/frontend/dist.

Secret generation: use a cryptographically secure generator/password manager.
For Windows PowerShell, this optional command copies a newly generated secret
straight to the clipboard WITHOUT printing it or writing a file:

~~~powershell
python -c "import secrets, subprocess; subprocess.run(['clip.exe'], input=secrets.token_urlsafe(64), text=True, check=True)"
~~~

This is an instruction for the owner, not executed during preparation.
First disable clipboard history/cloud sync and screen/session recording.
Paste only into Render's private DJANGO_SECRET_KEY field, then clear:

~~~powershell
Set-Clipboard -Value ''
~~~

Never reuse a Django key, DB password or exposed historical credential. Neon
generates DB role passwords; copy through approved private channels only. No
secrets in chat, screenshots, Git, command arguments, transcripts or build ARGs.
Review the historical exposure gate in RELEASE.md independently.

## Approval D: bounded staging smoke and voting enablement

After approved migration/deploy, obtain separate authorization for synthetic
registration/data writes, a restart, private-link operations and voting flags.
Use two normal test accounts; no public admin credentials or seed backdoors.

| Check | Required result |
| --- | --- |
| Startup/health | HTTPS /health/live/ and /health/ready/ return 200 expected JSON, no loop or HTML fallback |
| Static/deep link | /assets JS/CSS and /static/admin/css/base.css have correct MIME; /polls/id refresh serves React; API misses remain errors |
| Auth | Register/login, reload restores session, logout/revoked refresh fails; no JWT browser storage or refresh JSON |
| Cookie/CSRF | Secure/HttpOnly/Lax/auth path; missing/wrong token and untrusted Origin rejected; no wildcard credential CORS |
| Discovery/creation | Guest public list/search/category work; creator drafts/options/edit/publish are owned; hidden drafts/private polls never leak |
| Results/lifecycle | Check all three policies, closing/reopen relocking, archive read-only and expiration |
| Private share | Guest scoped read works; invalid/revoked/regenerated tokens rejected; never grants vote/edit permission |
| Vote/replacement | ONLY after reconciliation + separate staging write approval: complete replacement, limits, participant/selection totals, no double counting |
| Persistence | Restart ONLY the new staging service; synthetic poll/ballot/profile/revocation data survives; no DB reset |
| Cold start/capacity | Accept sleep/wake delay, review free usage/memory/CPU and correct retry behavior; stop if Free cannot sustain it |

Before any vote, record fresh schema/read-only reconciliation evidence, no old
writers/history anomalies, then approve enabling NEXUS_BALLOT_WRITES_ENABLED
ONLY on the staging service. bridge can remain the compatibility mode; switching
authority to ballots is a distinct gated choice. No production flag is changed.
Do not run backfill --apply on a fresh DB. Preserve source evidence if unexpected
history exists. Log booleans/counts/status, never credentials or voter choices.

Actual-host checks must include spoofed Host/protocol handling, externally
visible redirects, private cache policy and secure-cookie behavior. Resource-
limited local smoke and published CI do not prove these cloud behaviors.
Safari/Firefox, assistive technology, real devices and privacy/retention notices
remain manual public-launch gates.

## Backups, rollback and cost protection

Follow RELEASE.md for approved pg_dump, protected storage/checksums, restore
proof and lock budgets. Keep independent offline backups: Free history windows
are limited and are not durable backup retention. Do not restore over newer
votes or publish dumps. Approval is required for every restore target.

On failure pause staging voting writes first, preserve both stores/audit rows,
and roll back only to a reviewed schema-compatible, patched F-or-later artifact.
No migration reversal on populated ballot tables; prefer roll-forward. Never
switch to a legacy independent Vote writer, decrement auth_version or silently
repair data. Record RPO/RTO before exceptional data recovery approval.

No card, paid plan, autoscale upgrade, purchased domain, credits or paid jobs.
Use provider subdomains and manual deployment. Check Render workspace hours/
bandwidth/build minutes and Neon storage/compute/transfer in their usage pages.
Do not keep the service awake with bots. If allowance runs out, stop/wait for
reset; do not upgrade, auto-purchase or delete user data to hide the issue.

## Local verification and current go/no-go

Run existing isolated scripts from the selected pinned Python environment:

~~~powershell
python -B scripts/check_release.py
python -B scripts/audit_secrets.py
python -B scripts/verify_staging.py
python -B scripts/verify_fullstack.py --tests alx_project_nexus/tests/test_staging.py alx_project_nexus/tests/test_release_configuration.py alx_project_nexus/tests/test_settings.py
python -B -m flake8 --extend-exclude "*/migrations/*" accounts polls alx_project_nexus manage.py scripts integration
git diff --check
~~~

The resource-limited artifact and offline production checks passed locally.
QA.md records actual focused counts and CI evidence. The complete candidate
backend/frontend/integration/artifact jobs passed on GitHub; no cloud credential
was used. Full local suites were not repeated for this documentation/test-tool
change; the earlier complete two-run evidence remains in QA.md.

**GO for Approval A review only. NO-GO for deployment yet:** no actual staging
hostname, provider account confirmation, proxy attestation, approved connection/
migrations/grants/restore, synthetic write approval or real staging smoke exists.
No resource, migration, account connection, deployment, commit or push was
performed by this preparation. RELEASE.md is the single release checklist.


## Neon role setup: authorized owner-operated workflow

Owner reports project project-nexus-staging, branch production and database
nexus_staging created on Free, running PostgreSQL 18.6. The SQL below targets
major 18 (server_version_num 180000 through 189999); it is no longer guarded to
major 15. The compatibility review was offline. Owner-reported live connection
and preflight results are recorded below, separately from assistant verification.
Read-only inspection and configuration of exactly
nexus_staging_migrator and nexus_staging_runtime are now authorized. Migrations,
application data changes, Render creation/deployment, voting and recovery remain
UNAPPROVED. No private credential channel is available to the assistant: the
assistant has NOT executed or independently certified the steps against Neon.
The owner reports completing the initial connection/preflight only. The preceding
Approval A/B text is historical; this section records the narrower current gate.

### PostgreSQL 18 compatibility review and remaining gates

Reviewed against PostgreSQL 18 and current Neon documentation, without a database
connection, SQL execution, Docker resource creation or migration execution:

- Preflight: current_database/current_user, server_version_num, pg_roles,
  pg_namespace, pg_database, pg_class, pg_proc, pg_stat_ssl, pg_default_acl,
  privilege functions and to_regclass remain available. NULL ACLs mean built-in
  defaults, not no privileges; the queries below explicitly expand PUBLIC ACLs.
- Fresh PostgreSQL 18 normally gives PUBLIC USAGE, not CREATE, on public; its
  normal owner is pg_database_owner, whose implicit member is the database owner.
  PUBLIC CONNECT/TEMPORARY on databases remain defaults. Templates/upgrades and
  Neon may differ, so inspect actual ownership/ACLs and keep explicit revokes.
  Do not transfer schema/database ownership or modify neondb to normalize it.
- PostgreSQL 18 retains the explicit LOGIN/NOINHERIT/NOSUPERUSER/NOCREATEDB/
  NOCREATEROLE/NOREPLICATION/NOBYPASSRLS/PASSWORD NULL syntax and schema/database
  grants used here. No MD5 password configuration is introduced. Neon Console
  roles remain elevated by default; SQL-created roles and private generated
  password provisioning remain the chosen path, subject to actual Console support.
- Role membership is directional. PostgreSQL 18 may automatically grant the
  CREATEROLE creator ADMIN on each newly created role, with INHERIT/SET false by
  default. This is creator -> new-role administration, NOT new-role -> owner
  membership. It is not escalation of runtime. Audit admin_option, inherit_option
  and set_option in BOTH directions. Keep createrole_self_grant empty for this
  transaction. Do not revoke provider/bootstrap grants or alter existing roles.
  New roles must still be members of NO other roles; NOINHERIT alone would not
  prevent a SET-enabled membership from escalating privileges.
- Default SELECT-on-tables and USAGE-on-sequences syntax is unchanged. It applies
  to the actual creating role, hence connect directly as migrator for migrations.
  PostgreSQL 18 also supports MAINTAIN: do not grant it or ALL. No default table
  DML is granted; the explicit post-migration allowlist still excludes history.
- requirements.txt pins Django 5.2.18 and psycopg2-binary 2.9.11. Django 5.2
  supports PostgreSQL 14+, and psycopg2 2.9.11 updated error mappings for PG18.
  The inspected local Python environment imports these exact versions with
  libpq build/runtime 16.9. An older libpq is not itself a requirement to replace
  the server or dependency, but real PG18 TLS/SCRAM/authentication must be tested.
  The Docker Python 3.12 wheel/libpq must also be checked in the actual artifact.
  No dependency change is justified by this review alone.
- Existing migration SQL (concurrent unique index outside a transaction,
  UNIQUE USING INDEX, NOT VALID check/composite FKs, DEFERRABLE INITIALLY DEFERRED,
  and separate VALIDATE CONSTRAINT) is still supported by PG18. Ownership and
  lock requirements remain; the reviewed fresh/upgrade/reversal and concurrency
  suites previously used PG15, not PG18. No migration has been run by this review.
  Before staging migrations, rehearse the full chain and constraints, legacy/
  ballot compatibility and concurrent transactions on an approved disposable
  PG18 target. PG18 represents NOT NULL constraints in pg_constraint too; audit
  named application constraints and their convalidated/conenforced values, not
  assumptions that every catalog row is an application check/FK. The candidate
  does not use NOT ENFORCED and must not acquire it during rollout.
- Local psql is 17.6. Its ordinary SQL/TLS functionality can be used for these
  statements against 18; prefer matching psql 18 if already available. Avoid
  cross-major catalog-dependent slash commands; use the explicit SQL below.
  An older client warning is not evidence of successful server compatibility.
  For BACKUPS, pg_dump 17 or older MUST NOT be used against PG18: it refuses newer
  server majors. Use reviewed PG18 pg_dump/pg_restore and a compatible approved
  restore target. No client install, cloud backup or restore is authorized here.

Sources: [PostgreSQL 18 schemas](https://www.postgresql.org/docs/18/ddl-schemas.html),
[PUBLIC defaults](https://www.postgresql.org/docs/18/ddl-priv.html),
[role creation/automatic creator grants](https://www.postgresql.org/docs/18/role-attributes.html),
[membership options](https://www.postgresql.org/docs/18/catalog-pg-auth-members.html),
[default privileges](https://www.postgresql.org/docs/18/sql-alterdefaultprivileges.html),
[Neon roles](https://neon.com/docs/manage/roles),
[Django 5.2 database support](https://docs.djangoproject.com/en/5.2/ref/databases/),
[psycopg2 2.9.11 notes](https://www.psycopg.org/docs/news.html),
[backup client compatibility](https://www.postgresql.org/docs/18/app-pgdump.html).

Offline validation of this PG18 documentation update: all three PowerShell
blocks passed syntax parsing; six SQL blocks / 52 statements passed lexical and
security-guard checks (not a PostgreSQL grammar/runtime test). Network/database-
blocked production checks passed for frontend/static/API routing, Secure cookies
and CSRF; W005/W021 remained visible and explicitly acknowledged for synthetic
HSTS scope. The migration graph loaded without a connection, and all 15 model
constraints compiled with simulated server version 180006. Current-source secret
scan and git diff --check passed. No PG18 server, Neon role/password/TLS check,
fresh/upgrade/reversal migration or full backend suite was executed. Existing
PG15 CI is not PG18 evidence. Only STAGING.md changed during this update; the
other three existing preparation files were verified byte-for-byte unchanged.

### 1. Dashboard and private connection

In the Neon Console select project-nexus-staging, branch production. Confirm the
organization is Free/$0 with no trial/card/payment requirement. Stop otherwise.
Under Postgres database > Databases confirm nexus_staging and its owner; do not
change neondb or any existing role. Record region and PostgreSQL version locally.
Open Connect, choose this database and owner, turn Connection pooling OFF. Keep
the direct hostname and owner password private. Do not use Roles > Add role:
ordinary console-created roles are elevated. Do not run sample/data-import SQL.

Use a fresh PRIVATE Windows PowerShell window, without transcripts/recording or
clipboard history/sync. psql is already installed at the path below. This does
not read dotenv or change permanent environment settings. It downloads only a
PUBLIC CA certificate over verified HTTPS; no credentials are written to files.
The reviewed Linux artifact already has the Debian CA bundle instead.

~~~powershell
$ErrorActionPreference = 'Stop'
# Clear inherited libpq overrides in this fresh process only.
Get-ChildItem Env:PG* | ForEach-Object {
    [Environment]::SetEnvironmentVariable($_.Name, $null, 'Process')
}
$caPath = Join-Path ([IO.Path]::GetTempPath()) ('nexus-neon-ca-' + [guid]::NewGuid().ToString('N') + '.pem')
Invoke-WebRequest -UseBasicParsing 'https://letsencrypt.org/certs/isrgrootx1.pem' -OutFile $caPath
$privateHost = Read-Host 'Direct hostname from this project (hidden)' -AsSecureString
$env:PGHOST = [System.Net.NetworkCredential]::new('', $privateHost).Password
$privateHost.Dispose()
if ($env:PGHOST -notmatch '^ep-[a-z0-9-]+(?:\.[a-z0-9-]+)+\.neon\.tech$' -or $env:PGHOST -match '-pooler\.') {
    throw 'Stop: confirm the direct Neon hostname; do not substitute an IP or pooler.'
}
$env:PGDATABASE = 'nexus_staging'
$env:PGPORT = '5432'
$env:PGUSER = Read-Host 'Existing database owner role name'
$env:PGSSLMODE = 'verify-full'
$env:PGSSLROOTCERT = $caPath
$env:PGCONNECT_TIMEOUT = '15'
$env:PGAPPNAME = 'nexus-staging-role-preflight'
$env:PGOPTIONS = '-c statement_timeout=30000 -c lock_timeout=5000'
$psqlPath = 'C:\Program Files\PostgreSQL\18\bin\psql.exe'
if (-not (Test-Path -LiteralPath $psqlPath)) {
    $psqlPath = 'C:\Program Files\PostgreSQL\17\bin\psql.exe'
}
if (-not (Test-Path -LiteralPath $psqlPath)) {
    throw 'Stop: no reviewed psql client is installed.'
}
& $psqlPath -X -n -W -v ON_ERROR_STOP=1 -v VERBOSITY=terse -P pager=off
~~~

Enter the owner password ONLY at psql's hidden password prompt. Do not put it in
PowerShell, SQL, connection strings, env files or PGPASSWORD. You may inspect
\conninfo ONLY in the private terminal: it can reveal the host, role, database
and addresses. Never copy its full output, environment or connection objects
into shared logs/chat. Record only redacted TLS protocol/cipher and pass/fail.
If connection fails,
keep the error private (it may contain the hostname), stop and report only its
category. Never disable certificate/hostname verification. A successful direct
non-pooled connection with effective PGSSLMODE=verify-full, the correct direct
Neon DNS hostname and trusted CA verifies the client-to-Neon TLS peer. The direct
endpoint still uses Neon infrastructure; non-pooled does NOT mean bypassing the
Neon connection proxy. The SQL Editor alone cannot prove this libpq configuration.
The banner/\conninfo establishes encryption, not certificate verification by
itself: retain the explicit verify-full settings, no overriding DSN/service,
and successful connection evidence together.

### Client TLS versus PostgreSQL-backend SSL: corrected Neon interpretation

Reviewed 2026-11-09. The earlier requirement for pg_stat_ssl.ssl=true was
incorrect for Neon's TLS-terminating proxy path. Neon documents mandatory TLS
for Internet client connections and a proxy in front of compute. Its official
proxy implementation accepts/decrypts client TLS and establishes a separate
compute connection. PostgreSQL's pg_stat_ssl describes the backend connection,
not necessarily the original external client-to-proxy TLS session.

Keep these layers distinct:

| Evidence | Interpretation / requirement |
| --- | --- |
| Effective libpq sslmode=verify-full + trusted CA + correct hostname, successful connection | Required client-side certificate/hostname verification of the Neon endpoint; do not downgrade |
| psql SSL banner or private \conninfo showing TLS protocol/cipher | Required negotiated client-to-Neon encryption; alone does not prove certificate/hostname checks |
| SHOW ssl | PostgreSQL compute's own SSL setting, not the external proxy's setting; off is compatible with proxy TLS termination |
| pg_stat_ssl.ssl/version/cipher/bits | Backend-hop diagnostics; false/NULL can coexist with verified external TLS and is not a client TLS failure gate on this Neon path |
| inet_client_addr() IS NOT NULL | Backend sees a TCP peer; does not identify the original public client or prove encryption/absence of a proxy |

Do not require either true or false for the backend SSL diagnostics. They may
change with Neon routing/configuration. This interpretation applies to the
identified Neon proxy-backed deployment, not an arbitrary direct PostgreSQL
server. Never accept a non-TLS external connection, sslmode=prefer/require as a
substitute for verify-full, a CA/hostname error, or a missing client TLS indication.
Stop and investigate those failures without changing provider settings.

Owner-reported live evidence (not independently executed by the assistant):
psql 17.6 connected to PostgreSQL 18.6 with PGSSLMODE=verify-full; psql reported
TLSv1.3 / TLS_AES_256_GCM_SHA384 and private \conninfo confirmed SSL. SHOW ssl
was off, pg_stat_ssl.ssl was false and inet_client_addr() was non-NULL. Correct
database/version/owner, empty public schema, no existing target roles, expected
owner membership and provider ACL checks passed. These observations are
consistent with proxy TLS termination; the owner connection need not be marked
failed merely because compute-side SSL is off. No roles/migrations are inferred
to have been created by that successful preflight.

For EACH future migrator/runtime session: retain the step-1 direct-host,
verify-full and CA settings, supply only that role's password privately, then
check the actual psql SSL banner or private \conninfo. Record redacted protocol/
cipher and effective client mode. Run the backend SQL only as diagnostics.
For the later Django/Gunicorn image, separately verify psycopg/libpq's effective
verify-full options and client-side SSL negotiation from that actual artifact;
a psql owner session is not proof that the web runtime is configured correctly.

The public-client TLS session terminates at Neon infrastructure. These checks
DO NOT independently attest encryption/isolation of every provider-internal
transport or establish a single TLS session all the way to the PostgreSQL
process. Do not claim such end-to-end evidence, infer public plaintext from the
backend values, or change SHOW ssl through ALTER SYSTEM. Obtain provider
confirmation if internal-hop guarantees are required for the release review.
No paid private-networking feature is selected or required by this correction.

Sources (primary):
[Neon secure connections and verify-full](https://neon.com/docs/security/security-overview#secure-connections),
[Neon proxy definition](https://neon.com/docs/reference/glossary#neon-proxy),
[official proxy TLS handshake implementation](https://github.com/neondatabase/neon/blob/main/proxy/src/pglb/handshake.rs),
[separate compute connection implementation](https://github.com/neondatabase/neon/blob/main/proxy/src/proxy/mod.rs),
[PostgreSQL pg_stat_ssl scope](https://www.postgresql.org/docs/18/monitoring-stats.html#MONITORING-PG-STAT-SSL-VIEW),
[libpq verify-full](https://www.postgresql.org/docs/18/libpq-ssl.html).
The official source corroborates the two connections; it is not an attestation
of the exact hosted proxy version/configuration in this project.

### 2. Owner preflight: run read-only SQL first

Paste this into the owner psql session (or SQL Editor selected explicitly to
production / nexus_staging / its owner, AFTER the direct TLS test). Keep the
result grids private; only share pass/fail and aggregate counts, not role/host
inventories. Confirm major 18 (owner reports 18.6); stop if the server is a
different major. PostgreSQL 15 was the prior test baseline, not the staging
requirement. Do not upgrade/downgrade or recreate the database.

~~~sql
BEGIN READ ONLY;
SELECT current_database() = 'nexus_staging' AS correct_database,
       current_setting('server_version') AS server_version,
       current_setting('server_version_num')::integer BETWEEN 180000 AND 189999
         AS supported_major,
       current_user = pg_get_userbyid(datdba) AS connected_as_database_owner
FROM pg_database WHERE datname = current_database();
-- Diagnostics for the compute-side connection, NOT external TLS pass/fail.
SHOW ssl;
SELECT ssl AS backend_ssl, version AS backend_tls_version,
       cipher AS backend_tls_cipher, bits AS backend_tls_bits
FROM pg_stat_ssl WHERE pid = pg_backend_pid();
SELECT inet_client_addr() IS NOT NULL AS backend_has_tcp_peer;
SELECT nspname, pg_get_userbyid(nspowner) AS owner, nspacl
FROM pg_namespace
WHERE nspname NOT LIKE 'pg_%' AND nspname <> 'information_schema';
SELECT datacl FROM pg_database WHERE datname = current_database();
-- Expand NULL ACLs; grantee zero means PUBLIC.
SELECT a.privilege_type, a.is_grantable AS public_grant_option
FROM pg_database d
CROSS JOIN LATERAL aclexplode(COALESCE(d.datacl, acldefault('d', d.datdba))) a
WHERE d.datname = current_database() AND a.grantee = 0;
SELECT a.privilege_type, a.is_grantable AS public_grant_option
FROM pg_namespace n
CROSS JOIN LATERAL aclexplode(COALESCE(n.nspacl, acldefault('n', n.nspowner))) a
WHERE n.nspname = 'public' AND a.grantee = 0;
SHOW createrole_self_grant;
SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolreplication,
       rolbypassrls, rolinherit, rolcanlogin
FROM pg_roles
WHERE rolname = current_user OR rolname LIKE 'nexus_staging_%';
SELECT member.rolname AS member, parent.rolname AS granted_role,
       m.admin_option, m.inherit_option, m.set_option
FROM pg_auth_members m
JOIN pg_roles member ON member.oid = m.member
JOIN pg_roles parent ON parent.oid = m.roleid
WHERE member.rolname = current_user OR member.rolname LIKE 'nexus_staging_%'
   OR parent.rolname LIKE 'nexus_staging_%';
SELECT n.nspname, c.relname, c.relkind
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public';
SELECT n.nspname, p.proname, p.prosecdef
FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'public';
SELECT defaclrole::regrole, defaclnamespace::regnamespace,
       defaclobjtype, defaclacl FROM pg_default_acl;
COMMIT;
~~~

Require correct_database/supported_major/connected_as_database_owner=true,
PostgreSQL major 18, the CLIENT-side verified TLS evidence described above,
empty public relations/functions, no pre-existing target roles, and only
expected provider schemas/owner memberships. Backend SSL values are diagnostics,
not required to be true; SHOW ssl=off / backend_ssl=false is compatible with
Neon's separate TLS-terminating proxy connection. Review extra schemas, PUBLIC grants
and any security-definer routines; stop on unknown objects/privileges. No role
password hashes are queried. The SQL cannot attest the Neon billing plan,
project/branch names or that the copied hostname belongs to the intended project:
confirm those in the dashboard. Do not proceed on a mismatch or uncertainty.

### 3. Owner role setup: one guarded transaction, no passwords

Only after ALL preceding checks pass, execute this in the same correct database.
It intentionally fails if either role already exists; do not drop/reset/overwrite
an existing role or rerun around a failed guard. PUBLIC hardening affects only
nexus_staging and its public schema; it never issues commands against neondb.
No owner attributes or owner password are changed and no pre-existing
membership is manually changed. PG18's automatic creator ADMIN grant on the
new roles is expected where applicable; inspect its direction/options rather
than incorrectly treating it as a runtime administrative membership.

~~~sql
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL createrole_self_grant = '';
DO $guard$
BEGIN
  IF current_database() <> 'nexus_staging'
     OR current_setting('server_version_num')::integer NOT BETWEEN 180000 AND 189999
     OR current_user <> (SELECT pg_get_userbyid(datdba) FROM pg_database
                        WHERE datname = current_database()) THEN
    RAISE EXCEPTION 'STOP: target, version or owner mismatch';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname IN
      ('nexus_staging_migrator', 'nexus_staging_runtime')) THEN
    RAISE EXCEPTION 'STOP: target role already exists';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'public')
     OR EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = 'public') THEN
    RAISE EXCEPTION 'STOP: public schema is not empty';
  END IF;
END;
$guard$;
CREATE ROLE nexus_staging_migrator LOGIN NOINHERIT NOSUPERUSER
  NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD NULL;
CREATE ROLE nexus_staging_runtime LOGIN NOINHERIT NOSUPERUSER
  NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD NULL;
REVOKE CONNECT, TEMPORARY ON DATABASE nexus_staging FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE nexus_staging
  TO nexus_staging_migrator, nexus_staging_runtime;
GRANT USAGE, CREATE ON SCHEMA public TO nexus_staging_migrator;
GRANT USAGE ON SCHEMA public TO nexus_staging_runtime;
ALTER ROLE nexus_staging_migrator IN DATABASE nexus_staging SET search_path = public;
ALTER ROLE nexus_staging_runtime IN DATABASE nexus_staging SET search_path = public;
COMMIT;
~~~

Only the two new roles are created. PASSWORD NULL means they have no usable
password until the next step; it is not an empty password. NOINHERIT is defense
in depth, not a substitute for having no elevated memberships. Postgres roles
are branch-wide; these commands do not remove possible PUBLIC CONNECT to other
existing databases. Do not claim per-role denial of neondb or modify it to obtain
that denial. Neither role is granted data/schema privileges there.

In Neon, production > Postgres database > Roles, refresh the list. For EACH of
the two new SQL-created roles ONLY: role menu > Reset password > Reset. Store
its generated password directly in a private approved credential manager; no
screenshots, chat, shell variables, transcript or repository files. This is the
initial provisioning of a new role, not rotation of an existing owner. If a role
is absent, reset is unavailable, or an upgrade is requested, STOP: do not use
Add role, embed a plaintext SQL password, or reset the owner instead.

### 4. Migrator: defaults and rollback-only schema proof

Leave owner psql with \q. In the SAME fresh PowerShell window, set PGUSER below
and connect again; supply only that role's generated password at the hidden
prompt. Host, TLS, database and timeouts remain exactly as in step 1.

~~~powershell
$env:PGUSER = 'nexus_staging_migrator'
& $psqlPath -X -n -W -v ON_ERROR_STOP=1 -v VERBOSITY=terse -P pager=off
~~~

First verify CLIENT-side TLS for this migrator session using the unchanged
verify-full/CA/direct-host settings and psql's SSL banner or private \conninfo.
Step 2's backend SSL queries are diagnostic only; backend_ssl=false is not a
failure of verified client TLS. Then execute:

~~~sql
BEGIN;
DO $guard$
BEGIN
  IF current_database() <> 'nexus_staging'
     OR current_user <> 'nexus_staging_migrator' THEN
    RAISE EXCEPTION 'STOP: wrong migrator target';
  END IF;
END;
$guard$;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT ON TABLES TO nexus_staging_runtime;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE ON SEQUENCES TO nexus_staging_runtime;
COMMIT;

BEGIN;
CREATE TABLE public.nexus_m_permission_probe (id bigint PRIMARY KEY);
CREATE INDEX nexus_m_permission_probe_idx ON public.nexus_m_permission_probe(id);
ALTER TABLE public.nexus_m_permission_probe ADD COLUMN note text;
SELECT has_table_privilege('nexus_staging_runtime',
                          'public.nexus_m_permission_probe', 'SELECT') AS runtime_select,
       has_table_privilege('nexus_staging_runtime',
                          'public.nexus_m_permission_probe', 'INSERT') AS runtime_insert;
ROLLBACK;
SELECT to_regclass('public.nexus_m_permission_probe') IS NULL AS probe_removed;
~~~

Require runtime_select=true, runtime_insert=false, probe_removed=true. The probe
contains no rows and is rolled back, never a committed application table. If
any step fails, issue ROLLBACK (or disconnect) and stop. Do not persist a probe
table or call Django migrations. All actual migrations must later run AS THIS
migrator so object ownership/defaults apply; using the Neon owner would not do so.

IMPORTANT: PostgreSQL default ACLs cannot exclude a table by name. Therefore
never grant default INSERT/UPDATE/DELETE on ALL future tables: that would make
new django_migrations writable. Future tables automatically receive SELECT and
sequences USAGE, but application DML is an explicit allowlist grant AFTER EACH
approved migration, before web traffic. Unknown future tables fail closed.
No event trigger or automatic migration/grant mechanism is introduced.

### 5. Runtime verification, no app data changes

Quit psql, reconnect with the runtime's own password:

~~~powershell
$env:PGUSER = 'nexus_staging_runtime'
& $psqlPath -X -n -W -v ON_ERROR_STOP=1 -v VERBOSITY=terse -P pager=off
~~~

Verify CLIENT-side TLS for this runtime session just as for the migrator;
record only redacted negotiated protocol/cipher plus effective verify-full.
Run these read-only checks. Step 2's backend SSL queries remain diagnostic only;
never substitute their values for client-side verification.

~~~sql
BEGIN READ ONLY;
SELECT current_database() = 'nexus_staging' AS correct_database,
       current_user = 'nexus_staging_runtime' AS correct_runtime,
       has_schema_privilege(current_user, 'public', 'USAGE') AS schema_usage,
       has_schema_privilege(current_user, 'public', 'CREATE') AS schema_create,
       has_database_privilege(current_user, current_database(), 'CREATE') AS db_create,
       has_database_privilege(current_user, current_database(), 'TEMPORARY') AS db_temp;
SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolreplication,
       rolbypassrls, rolinherit, rolcanlogin
FROM pg_roles WHERE rolname IN ('nexus_staging_migrator', 'nexus_staging_runtime');
SELECT count(*) AS target_memberships
FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.member
WHERE r.rolname IN ('nexus_staging_migrator', 'nexus_staging_runtime');
SELECT count(*) AS runtime_owned_relations
FROM pg_class WHERE relowner = (SELECT oid FROM pg_roles
                              WHERE rolname = 'nexus_staging_runtime');
SELECT to_regclass('public.django_migrations') IS NULL AS history_not_created;
COMMIT;
~~~

Require correct_database/correct_runtime/schema_usage/history_not_created=true;
schema_create/db_create/db_temp=false; target_memberships/runtime_owned_relations=0.
All five dangerous role flags and rolinherit must be false; rolcanlogin=true.
These checks demonstrate capabilities via effective privileges and memberships;
no extra test role/database is created. They do NOT prove application table
access or a rejected ALTER/INSERT on tables that do not exist yet.

An optional actual denied-CREATE test (no committed object, no application data):

~~~sql
BEGIN;
DO $probe$
BEGIN
  BEGIN
    CREATE TABLE public.nexus_m_runtime_denial_probe(id integer);
    RAISE EXCEPTION 'STOP: runtime unexpectedly has CREATE';
  EXCEPTION WHEN insufficient_privilege THEN
    RAISE NOTICE 'PASS: runtime CREATE denied';
  END;
END;
$probe$;
ROLLBACK;
~~~

Require the PASS notice. An unexpected exception stops psql; disconnect/ROLLBACK
before anything else. Never COMMIT the probe. In the private owner session,
repeat the role/membership checks after dashboard password provisioning to
confirm neither new role became a member of any elevated role or of each
other. Existing owner/internal grants must remain intact. The possible new
creator ADMIN grants point FROM the creator TO the two new roles (shown as
member=creator, granted_role=new role); expect admin_option=true,
inherit_option=false, set_option=false with the setup transaction's empty
createrole_self_grant. Do not remove those server-managed grants or add manual
grants to existing roles. Unexpected directions/options require a stop.

### 6. Future post-migration grants: PREVIEW ONLY, DO NOT RUN NOW

Migrations remain unapproved. There is no django_migrations table to validate yet.
When separately approved migrations finish, review actual tables/owners versus
this candidate, then as nexus_staging_migrator grant DML to this explicit table
allowlist (includes existing admin/comment routes; migration history excluded):

~~~sql
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE
  public.accounts_user, public.accounts_userprofile,
  public.accounts_user_groups, public.accounts_user_user_permissions,
  public.auth_group, public.auth_group_permissions, public.auth_permission,
  public.django_content_type, public.django_session, public.django_admin_log,
  public.token_blacklist_outstandingtoken, public.token_blacklist_blacklistedtoken,
  public.polls_category, public.polls_poll, public.polls_option, public.polls_vote,
  public.polls_comment, public.polls_auditlog, public.polls_ballot,
  public.polls_ballotselection, public.polls_pollsharetoken
TO nexus_staging_runtime;
GRANT SELECT ON TABLE public.django_migrations TO nexus_staging_runtime;
~~~

Wrap the future reviewed grant step in a transaction; absent/unexpected tables
or owners must abort, not be skipped. Do not grant ALL, TRUNCATE, REFERENCES,
TRIGGER, MAINTAIN, schema CREATE, grant options, table ownership, broad data roles or
migrator membership. Default sequence USAGE does not grant table mutation or
sequence reset; it is required for ORM integer-key inserts.

Before Render, test real app operations/SELECT under runtime, prove history
INSERT/UPDATE/DELETE/TRUNCATE denied and table ALTER denied with rollback-only
checks, verify read-only SELECT django_migrations for readiness, inspect all
schema owners/default ACLs, and rerun reconciliation under its separate gate.
The raw SQL runtime role necessarily has application DML: API authorization,
audit integrity and the voting/recovery feature gates remain required. Do not
mistake SQL grants for per-user poll/ballot access enforcement.

### 7. Cleanup and evidence (no secret output)

Quit psql. Close the fresh PowerShell window to discard process-only connection
values, or explicitly clear them first. Keep the two passwords only in the
approved private credential manager. The CA file is public, not a secret; no
password file was created. Do not save any connection URL or copy .env.local.
Do not expose raw connection errors or query inventories in shared logs/chat.

Record only: Free/no-card confirmed; intended project/branch/db confirmed;
major version; owner/empty-schema checks pass/fail; per-role CLIENT verify-full
and negotiated TLS protocol/cipher; backend-hop observations labelled diagnostic
only; roles/defaults created;
no memberships; schema privilege checks; probe rollback success. Actual
checks remain NOT RUN until the owner executes this workflow. Stop on any
unexpected item; no automatic repair, password workaround or extra approval
for already authorized routine steps is needed.

Render's future private environment values remain the inventory above:
POSTGRES_USER=nexus_staging_runtime, POSTGRES_DB=nexus_staging, POSTGRES_PORT=5432,
POSTGRES_SSLMODE=verify-full, POSTGRES_SSLROOTCERT=/etc/ssl/certs/ca-certificates.crt.
POSTGRES_HOST and POSTGRES_PASSWORD enter only Render's approved secret fields
at the later deployment gate. Migrator/owner credentials never enter Render.
Keep NEXUS_BALLOT_AUTHORITY=bridge, NEXUS_BALLOT_WRITES_ENABLED=false,
NEXUS_PASSWORD_RESET_ENABLED=false and NEXUS_PASSWORD_RESET_APPROVED=false.

Status: role/connection PREPARATION ready for authorized manual execution;
Neon NOT YET certified ready for Render. Remaining gates: actual private
execution/results, backup/restore and migration approval, post-migration DML/
history-denial tests, proxy/host evidence, Render creation/deploy approval,
then separately approved synthetic writes/voting/persistence smoke.

Current role/TLS instructions were checked against official documentation:
[Neon roles/password provisioning](https://neon.com/docs/manage/roles),
[Neon TLS/CA configuration](https://neon.com/docs/connect/connect-securely),
[PostgreSQL 18 default privileges](https://www.postgresql.org/docs/18/sql-alterdefaultprivileges.html).
Actual provider-account and database checks remain operator-run, not inferred
from public documentation or local syntax checks.

Documentation-only TLS correction (2026-11-09): owner live results above are
reported evidence, not new assistant database tests. No cloud connection, SQL,
role creation, migration, voting/recovery enablement or deployment was performed.
Existing authorization restrictions and all earlier preparation work remain.


## Current local-verification handoff (2026-11-13)

The owner confirms Neon project/branch/database and BOTH restricted roles are
already provisioned and verified. Earlier role-creation/password-reset blocks
are retained as historical procedure, NOT instructions to recreate or reset
those existing roles. No Neon connection was used for this local run.

Fresh pinned Python environment, complete PG18 backend/schema/concurrency suite,
synthetic PG18 dump/restore and a local restricted-role parity rehearsal passed;
QA.md contains exact counts/scope. PostgreSQL 18 local binary/client tools were
18.7; the reported Neon server is 18.6. Confirm the actual remote patch/version
and schema only in the separately approved cloud preflight.

Repeatable repository commands in a working pinned environment:

~~~powershell
python -B scripts/check_release.py --frontend-dist frontend/dist
python -B scripts/audit_secrets.py
python -B scripts/verify_fullstack.py
python -B scripts/verify_fullstack.py --postgres-major 18
python -B scripts/verify_staging.py
~~~

The PG15 default full-stack gate passed in full. PG18 was verified by a separate
334-test backend run plus --postgres-major 18 --integration-only (20 real live
checks), avoiding an unnecessary duplicate backend run. The image option never
adopts nexus-staging-test-db; it provisions an owned tmpfs instance on 55434.
PG18 tmpfs covers /var/lib/postgresql; PG15 retains /var/lib/postgresql/data.
No persistent volumes are accepted, and pre-existing resources are inventoried.

For backup comparison, PG18 pg_dump/reparse can change representation of
varchar-array-to-text casts in CHECK definitions. Compare exact row/history/
column/index/sequence content and constraint metadata, canonicalize equivalent
predicate formatting through the PG18 parser, and verify actual CHECK rejection.
Do not modify constraints or discard differences blindly to obtain a pass.
The local rehearsal used --exit-on-error --single-transaction --no-owner --no-acl
and retained historical Vote rows with reconciled native/imported ballots.

The fresh verification venv and sanitized evidence are retained in a task-owned
OS temporary directory for review/reuse, never a source of staging credentials.
Only task-created DBs/roles and labelled container stacks were cleaned. The
existing local container/volume and .env.local were preserved.

GO for reviewing a separately authorized Neon pre-migration preflight and backup;
NO-GO for automatic cloud migrations, Render resource creation/deployment,
voting/recovery enablement or Git publication. Local parity verifies the proposed
role/grant design, not actual cloud role state. Keep the post-migration explicit
DML allowlist and migration-history SELECT-only gate. RELEASE.md remains the
single operator checklist.
