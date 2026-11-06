# Disposable full-stack verification (Milestones I and J)

From the repository root in Windows PowerShell, with the existing Python
environment activated:

```powershell
docker info --format '{{.OSType}}' # Must be linux on the local Docker engine.
python -B scripts/verify_fullstack.py
```

Prerequisites: the pinned Python requirements already installed, Node 22.14+
and npm, Docker Desktop's Linux engine, an existing postgres:15 image, and
installed Google Chrome. Playwright is a test-only dependency in the frontend
lockfile; Chrome is used without downloading another browser. No production
service, SMTP server, Redis instance, hosting change, or root dotenv file is
needed.

The default command runs these gates, then cleans up:

1. Verify the local named-pipe/Unix-socket Docker endpoint and free loopback ports.
2. Copy frontend source to a new OS temporary directory, excluding dependencies,
   build artifacts and all dotenv files. Run npm ci, ESLint, strict application
   **and E2E** TypeScript, all frontend unit tests, and the production build there.
   This leaves an existing developer Vite process and its Windows-locked native
   dependencies untouched. Live Vite and Playwright use this same tested copy.
3. Create only a newly named, ownership-labelled PostgreSQL 15 container.
   Bind 127.0.0.1:55434; use temporary memory storage with no persistent volume.
   Generate a database/user in the nexus_test_i_* namespace and credentials in
   process memory. Passwords are passed by environment variable name, never
   command arguments or logs.
4. Select alx_project_nexus.settings_test explicitly. Run Django checks,
   makemigrations --check --dry-run, and the entire backend PostgreSQL suite.
5. Let pytest-django create/migrate a fresh test_nexus_test_i_* database.
   Its live-server fixture binds only 127.0.0.1 on an automatically chosen port.
   Start an owned Vite process on 127.0.0.1:5181 and proxy /api/ to that server.
   Wait for that Vite process's own startup announcement before probing readiness.
6. Execute real HTTP journeys, harness guard tests, and real desktop/headless
   Chrome plus desktop/tablet/mobile QA (1280/768/390px), automated axe WCAG checks,
   keyboard voting/confirmation/menu checks, enlarged text and reduced motion.
   Application responses are not
   mocked. Browser traffic is restricted to the local origin.
7. Stop only the owned Vite process; pytest destroys its test database.
   Remove only the container carrying this invocation's ownership nonce.
   Delete owned temporary directories and verify existing container, volume and
   network inventories were preserved. A failed assertion takes the same cleanup
   path. No prune, volume removal, existing database reset or production backfill
   is performed.

Do not kill the process forcibly: allow its finally blocks to clean up. If the
machine or Docker engine crashes, an ownership-labelled nexus-i-* container can
remain; inspect its label and obtain explicit approval before removing a stale
resource. The runner never adopts or overwrites a pre-existing container.

## Focused reruns

These reuse already installed frontend dependencies but still provision a fresh
owned PostgreSQL container/test database and a new local Vite process:

```powershell
python -B scripts/verify_fullstack.py --integration-only
python -B scripts/verify_fullstack.py --browser-only
python -B scripts/verify_fullstack.py --tests accounts/test_legacy_throttling.py
python -B scripts/verify_fullstack.py --integration-only --http-only
python -B -m flake8 --extend-exclude "*/migrations/*" accounts polls alx_project_nexus manage.py scripts/verify_fullstack.py scripts/start_local.py integration
git diff --check
```

--http-only explicitly reports browser verification as skipped. It is not the
full acceptance gate. Direct pytest integration or npm run test:e2e without the
runner's owned-resource context fails closed. The default backend pytest
testpaths are unchanged, so backend CI does not silently acquire Node/Chrome
requirements. Frontend CI remains a separately reviewed release task.

## Security and coverage

- Only NEXUS_TEST_* database credentials are used; production/Django/Postgres
  overrides are removed from child environments. settings_test never loads
  the production .env or local .env.local.
- Local HTTP uses the existing explicit test cookie settings: HttpOnly refresh
  cookies, SameSite=Lax, Path=/api/v2/auth/, Secure=False only for this isolated
  HTTP origin. Production cookie settings remain unchanged. CSRF stays enabled;
  same-origin proxy requests require no wildcard CORS or trusted-origin bypass.
- Password recovery stays disabled and email uses Django's in-memory backend.
- Tests cover registration, CSRF rejection, login/restoration, refresh replay,
  password/profile changes, revocation, draft/option editing, publication,
  discovery/category filtering, complete-set replacement, result policies,
  lifecycle changes, private fragment links and regeneration/revocation.
- Bridge mode and enabled ballot writes are set **only in the generated test
  environment**. Historical Vote fixtures are inserted only in the disposable
  test database. Dry-run/import/restart/reconciliation and ballot-only reads are
  tested there; source identifiers/timestamps remain unchanged and inconsistent
  ledgers fail closed. No production authority switch or repair occurs.
- Browser traces, screenshots, videos and storage-state files are disabled.
  The custom reporter prints controlled test/step names and source locations,
  never raw request bodies, credentials, DOM snapshots or exception payloads.
  Any optional share diagnostic contains booleans and a request count only.
- The real-browser regression reopens a private fragment link after refresh:
  the accepted capability must survive a deferred Router commit. The focused
  unit regression reproduces the previous duplicate-resolution race.

The disposable stack is a verification environment, not a production server.
Existing production proxy/HTTPS, host/origin, static serving, credentials,
hosting-trigger and ballot rollout/reconciliation gates remain in force.
Manual assistive-technology and additional browser-engine reviews remain release
checks; desktop Chrome with an emulated mobile viewport is not Safari/device
certification.

## QA-specific checks

The six QA browser journeys audit guest and creator screens at three viewports.
They include real forms/errors, private links and their unavailable state,
confirmation focus, native radio keyboard voting, results table, reduced motion,
200% CSS text scaling, 320-CSS-pixel reflow, and retry after a deliberately aborted transport request.
The latter aborts a real local request; it does not fabricate application data.
Axe is the existing locked dependency and checks contrast as well as tagged
WCAG 2.2 AA rules. This is not a claim of complete WCAG conformance or a
substitute for NVDA/VoiceOver, real-device and browser zoom testing.

`--tests`/`--backend-tests` accepts only existing paths within the backend or
integration test directories. It runs selected tests on disposable PostgreSQL,
skipping the unrelated frontend build. Always run the default command for the
final complete gate. No persistent database is used for these tests.
