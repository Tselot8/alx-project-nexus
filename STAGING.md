# Project Nexus: staging and portfolio launch preparation

**PREPARATION ONLY. No cloud resource or deployment is authorized.**
Research checked 2026-11-06. All account eligibility, regions and limits must be
rechecked before signup. Never supply a payment card or select a paid plan for
this milestone. The legacy main service remains separate and unchanged.

## Hosting recommendation (provisional, owner approval required)

**Primary:** one new free Render web service serving the combined Docker artifact
(React, Gunicorn, WhiteNoise and DRF on one HTTPS origin), with a separate Neon
Free PostgreSQL project. Use provider subdomains; a purchased custom domain is
unnecessary. This is an inference from the documented capabilities, not a
verified deployment or a guarantee of free account eligibility.

**Fallback:** the same unified artifact with Supabase Free PostgreSQL if Neon
eligibility, connectivity or quotas do not fit. This substitutes the database,
not Django authentication or the voting model. Verify a direct/session-mode
PostgreSQL endpoint and IPv4/TLS compatibility; transaction-pooler assumptions
are not approved for concurrent-index migrations or session-level operations.

| Option | Verified public details | Constraint / suitability |
| --- | --- | --- |
| Render unified web | Free compute: 512 MB, 0.1 CPU; managed TLS, environment configuration, Docker support | Sleeps after 15 idle minutes; cold start around a minute. Ephemeral filesystem; 750 workspace hours/month, shared with existing free services. External-DB traffic can trigger suspension. No free shell/one-off jobs; SMTP ports 25/465/587 blocked. No SLA; acceptable only as a limited portfolio candidate. |
| Neon Free database | Pricing currently lists no card/no time limit, 1 GB/project, 100 CU-hours/project/month, 5 GB egress/project; scales to zero after 5 idle minutes | Persistent PostgreSQL storage survives compute sleep. Free restore history is limited (6h or 1 GB changes); independent backups required. Region, CA trust, quota exhaustion and account admission still need validation. |
| Supabase Free database | Two projects, 500 MB database/project; low activity can pause projects after seven days | Requires owner unpause/readiness checks, independent backups, endpoint/IPv4 review. Card-free signup eligibility not confirmed for this account. |
| Cloudflare Pages frontend | Free: 500 builds/month, 20,000 files, 25 MiB/file; managed static hosting | Static assets fit. Separate hosting requires a reviewed same-origin API proxy, cache exclusions and cookie/header forwarding. Static Pages alone cannot run this PostgreSQL/Django backend. Not the initial recommendation. |
| Render Static Site frontend | Free CDN, TLS, branch-controlled builds | Same split-origin/proxy concerns. Combined artifact is simpler for current memory-only access tokens and HttpOnly refresh cookies. |
| Koyeb | Free instance exists, but official billing FAQ requires a card | Excluded under the no-card constraint. |
| PythonAnywhere Free | Built-in/external PostgreSQL needs a paid plan | Excluded without changing architecture. |
| Render Free PostgreSQL | Expires after 30 days | Excluded for persistent portfolio data. |

Render docs describe operating without a payment method, but do not guarantee
that this account can create a new free service without identity/card checks.
The owner must verify that dashboard step without creating anything yet. If a
card or payment is demanded, stop; neither primary nor fallback is approved.
Both depend on free Render compute eligibility. No independently verified,
card-free alternative Django compute host is asserted. CI uses PostgreSQL 15;
verify the selected provider version and rehearse migrations on the same major
version in a disposable environment before approving that target.

Official sources (live policy, not old blog quotas):
- [Render free limitations](https://render.com/docs/free)
- [Render compute resources](https://render.com/docs/compute-plans)
- [Render static/TLS](https://render.com/docs/static-sites)
- [Neon current pricing](https://neon.com/pricing)
- [Supabase free PostgreSQL](https://supabase.com/kb/faqs/platform/free-postgres-for-side-projects)
- [Supabase pausing](https://supabase.com/docs/guides/platform/free-project-pausing)
- [Cloudflare Pages limits](https://developers.cloudflare.com/pages/platform/limits/)
- [Koyeb card requirement](https://www.koyeb.com/docs/faqs/pricing)
- [PythonAnywhere database restrictions](https://help.pythonanywhere.com/pages/KindsOfDatabases/)

## Local artifact and serving contract

Dockerfile.staging requires Docker BuildKit and is an explicit opt-in alternative; the legacy Docker/Compose
paths are not changed. It uses Node 22 and Python 3.12 base-image families,
installs locked dependencies, builds Vite, and collects Django static files
with synthetic offline configuration. Record reviewed image digests/SBOM and
scan base images at release: tags are patch-updated, not immutable approvals.

Runtime is non-root Gunicorn, one worker/two threads for small instances.
Gunicorn does not independently trust forwarded headers. Access logs are disabled;
Django server logs contain only generic status metadata, not URLs, bodies,
headers or tracebacks. Host logs/ingress/analytics are separate manual controls.
Do not log Authorization, Cookie, X-Poll-Share, reset bodies or query strings.
Review restricted error investigation and alerting so redaction does not hide
persistent failures.

NEXUS_SERVE_FRONTEND=true activates the reviewed frontend/dist artifact.
Default false preserves the legacy backend root redirect. Local/test settings
always retain Vite. In production:
- /api/, /admin/, /swagger/ and /redoc/ remain Django endpoints.
- /assets/ serves only the validated public Vite assets directory.
- /static/ serves collected admin/DRF assets from static-build (not the
  historical tracked staticfiles). No wildcard static CORS is added.
- Frontend deep links return the same index, private/no-store and no-referrer.
  Reserved API/static namespaces and file-like paths never return SPA success.
- The frontend keeps relative /api/ requests; no production Vite proxy or
  cross-origin token storage is introduced.
- SecurityMiddleware precedes artifact serving; allowed Host is checked before
  static responses. HTTPS redirects and Secure cookies stay enforced.

Build and startup NEVER migrate, seed, backfill, reconcile, change authority,
create users or enable writes. No secrets are image build args.
.dockerignore allowlists application inputs and excludes env files, Git history,
node_modules, local databases, dumps and generated artifacts.

## Verification commands (Windows PowerShell, local-only)

Use the reviewed Python environment with requirements installed. The local
development venv is not automatically upgraded. Commands do not load .env.local
unless using the existing local startup script explicitly.

~~~powershell
python -B scripts/check_release.py
python -B scripts/audit_secrets.py
python -B scripts/verify_fullstack.py
python -B scripts/verify_staging.py
python -B -m flake8 --extend-exclude "*/migrations/*" accounts polls alx_project_nexus manage.py scripts integration
git diff --check
~~~

verify_fullstack owns temporary PostgreSQL and Django/Vite/Chrome processes.
It checks migration consistency, backend, frontend npm ci/lint/types/unit/build,
HTTP journeys and browser accessibility. The integration fixture now uses the
same HTTP readiness probes as start_local.py, rather than a colored startup
banner. Do not infer that this explains the remote CI failure without its logs.

verify_staging downloads public base images/packages, builds an owned local
image, exercises actual production middleware and collected assets, then starts
non-root Gunicorn in a network-disabled, unpublished local container. It probes
liveness, unavailable-DB readiness, SPA and CSRF. All environment credentials are
synthetic; no database connection can reach any service. It removes only its
own nonce-labelled image/container. Build cache can remain. This is artifact
verification, **not a staging deployment** or PostgreSQL persistence proof.

Health endpoints allow GET/HEAD:
- /health/live/ returns generic status=ok without database access.
- /health/ready/ performs bounded read-only SELECT 1 and migration-plan checks; unavailable or pending schema returns 503
  with generic status=unavailable. It never applies migrations or claims SMTP, voting
  reconciliation or launch approval. Use a low-frequency provider probe and
  external limits; excessive probes can consume free compute.
- HTTPS and Host rules apply to both. A platform HTTP health probe needs the
  reviewed ingress header/TLS path; do not exempt health from HTTPS to fix it.

## Approval-gated staging setup (do not execute automatically)

1. Resolve K CI first. K SHA 853ab4f15b8e163f2f0fcce312cc4eafed322a28:
   [run 42244485788](https://github.com/Tselot8/alx-project-nexus/actions/runs/42244485788)
   finished FAILED. Backend and frontend passed; full-stack failed in
   Verify isolated full stack. Public job-log API returned 403; no detailed
   failure cause is asserted. Owner must inspect restricted logs safely.
2. Approve hosting and no-card eligibility, region, free quotas, expected cold
   start and availability limitations. Do not attach the existing legacy main
   service or its database. Approve a new staging resource/DB identity.
3. Approve exact code SHA and separately approved publication, then create the
   new resources manually. Disable auto-deploy/PR previews/deploy hooks; use
   manual release selection. Do not connect main or enable production triggers.
4. Configure a NEW staging database and distinct random app signing secret,
   restricted DB role and domain. Never copy local or production records or
   credentials. Review DB TLS with verify-full and provider CA. Prefer direct
   endpoint for migration/preflight. If using a pooler, prove session semantics.
5. Load .env.production.example's contract through the approved secret store.
   Keep DJANGO_SETTINGS_MODULE=alx_project_nexus.settings, DEBUG false,
   NEXUS_SERVE_FRONTEND=true. Set exact allowed Host and HTTPS CSRF origin.
   Prefer empty CORS list; cross-origin credentials remain disabled.
6. Verify the actual ingress strips caller protocol headers, sets the trusted
   HTTPS indicator, preserves approved Host and prevents direct spoofing.
   Only then approve trusted proxy mode and its attestation flag. Keep secure
   cookies and redirects; review HSTS as in RELEASE.md.
7. Keep bridge authority, ballot writes false, and recovery disabled/unapproved.
   Run configuration-only release_preflight first. A free host lacking shell/
   jobs requires a separately approved management workstation/container; never
   move migrate into build/start commands to work around the limit.
8. Before DB connection or migration, obtain identity/access/backup approval.
   Review migrate --plan and SQL on a disposable copy. Operator explicitly runs
   migrate only after backup/restore and migration gates in RELEASE.md.
9. Check liveness/readiness, static/admin CSS, JS MIME and SPA deep-link routing.
   Verify API misses return errors, not index.html. Test spoofed Host/protocol,
   malicious Origin, missing CSRF, secure cookie flags and private cache headers.
10. Use approved synthetic actors for live staging smoke. Keep passwords and
    share links out of screen recordings, tickets, URLs beyond fragments and
    analytics. Verify login, refresh/revocation, draft creation/publish, filters,
    private read-only sharing, lifecycle, result policies and expired votes.
11. For voting smoke, obtain separate staging write approval after reconciliation
    shows a fresh/ready schema and no competing writers. Enable ONLY staging
    writes, under recorded operator approval. Production flags remain unchanged.
12. Complete browser/assistive-technology checks and resource/abuse monitoring.
    Public launch needs a new go/no-go review, not just a green readiness probe.

## Persistence, backup and recovery gates

Persistence resides exclusively in the approved external PostgreSQL service,
not in an ephemeral web filesystem. No local/production copy is part of setup.
Free database restore windows are not durable backups. Follow RELEASE.md for
protected PGPASSFILE/secret injection, custom pg_dump, checksums, encrypted
retention and restore into a NEW empty disposable database. No credentials in
CLI arguments, repository files, chat or ordinary logs.

After staging-specific approval, create a harmless synthetic poll through the
UI, record its identifier privately, restart only the staging web instance, and
verify poll/options/ballot totals and login revocation state survive. Verify
provider DB sleep/wake too; do not reset/drop the DB or touch existing volumes.
Record observation and capacity/retention limits. This persistence test has NOT
been run on a real provider during L.

Use separate migration and least-privilege runtime credentials where practical.
PostgreSQL same-poll composite FKs, uniqueness and auth_version remain required.
Run the read-only preflight before and after approved migrations. Do not run
historical backfill or authoritative cutover at deployment startup.

Rollback: pause approved writes, preserve both vote stores and audit evidence,
record incident state and select the previous reviewed schema-compatible,
security-patched artifact. Keep the database intact. Follow RELEASE.md's
explicit bridge/cutover approvals; never roll back to a Vote-only writer,
decrement auth_version, reverse populated ballot tables, or restore over newer
participation. Restore/data repair requires separate recovery approval and RPO
assessment.

## Optional portfolio fixtures (manual, fresh staging only)

No automatic seed command, password or public admin/demo account is added.
After NEW staging identity and write approval, the owner may register a normal
creator and a second ordinary participant through the real UI. Use:
- One public single-choice poll with neutral topic and two options.
- One multiple-choice poll (min=1, max=2), policy after_voting.
- One after_closing poll to exercise close/reopen relocking.
- One private poll for scoped read-only sharing and revoke/regenerate checks.
Publish through normal validation. Submit/replace ballots with the second
actor; confirm exact participant/selection totals, then exercise lifecycle.
Use no personal responses, sensitive questions, fake engagement or fabricated
metrics. Never delete published polls; close/archive as normal. Keep demonstration
accounts private and ordinary; visitors register their own accounts.

The existing public homepage/discovery needs no login. Voting, draft management
and profile/password actions retain real authentication and ownership. Recovery
UI remains explicitly unavailable while delivery is disabled; no false email
success or token disclosure is introduced.

## Public-launch no-go criteria

Use RELEASE.md's single checklist. Block launch for failed/unverified candidate
CI, unresolved exposed credentials, unverified proxy/TLS/hosts, missing restore
proof, migration/data anomalies, unapproved voting transition/write enablement,
unreviewed abuse controls, failed real staging smoke/persistence or unresolved
high-severity bugs. Manual screen-reader/cross-browser checks still apply.
Do not promise uptime on free tiers. Do not enable SMTP on Render Free (blocked
ports); a separate approved delivery solution/host is needed before recovery.
