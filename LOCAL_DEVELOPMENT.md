# Local development on Windows

Run in PowerShell from `C:\Projects\Project-Nexus` with the existing Python
virtual environment activated. Do not use the downloaded source folder as the
working directory. Python requirements, Node and `frontend/node_modules` must
already be available; install the locked frontend dependencies with `npm ci`
from `frontend/` if needed.

## Existing persistent database

The established local service is `nexus-a2-verify-db-local-1`, project
`nexus-a2-verify`, service `db-local`, PostgreSQL 15. Its binding is
`127.0.0.1:55433`; its persistent volume is `project-nexus-local-pgdata`.
The existing development database/user are `nexus_local_dev`/`nexus_local_user`.
Other containers and ports are unrelated and must be left alone.

```powershell
docker context show
docker info --format '{{.OSType}}' # Linux, local Docker Desktop engine.
docker ps --filter name=nexus-a2-verify-db-local-1 --format '{{.Names}} {{.Ports}}'
# Only if this exact existing container is stopped:
# docker start nexus-a2-verify-db-local-1
python -B scripts/start_local.py --check
python -B scripts/start_local.py
```

Keep the existing credentials in Git-ignored `.env.local` at the repository root.
The user-provided file is not an example and must not be overwritten. For a new
machine, review `.env.example` and obtain local-only credentials separately.
Never copy a production `.env`, print credentials, or put passwords in commands.
Changing environment variables does not reset an existing PostgreSQL password.
Do not run Compose under a different project name against this shared volume.
Do not recreate databases, remove volumes, reset passwords, or migrate as part
of normal startup.

The command loads `.env.local` literally (no variable interpolation), drops
inherited production/test database overrides, selects `settings_local` before
Django imports, and checks the database identity/migration state read-only.
It refuses pending migrations: backup and an explicit migration decision are
separate tasks. It never creates a database or applies migrations.

Startup readiness probes Django, Vite and then the API proxy over HTTP; it does
not depend on colored or buffered startup banners. Failures name the component
and include bounded, sanitized child logs.

Django runs at `http://127.0.0.1:8000`, Vite at `http://localhost:5173`.
Use the Vite URL; `/api/` uses its same-origin proxy. Only local settings disable
HTTPS redirects/secure cookies for local HTTP. Production security is unchanged.
Email is captured in memory and password recovery stays disabled.

Ctrl+C stops only the two owned servers, leaving PostgreSQL and data running.
Occupied ports cause a safe refusal; stop your own server or select
`--api-port 8001 --frontend-port 5174`. Custom frontend ports must also match any
explicit local origin allowlists. To verify startup/proxy and stop immediately:

```powershell
python -B scripts/start_local.py --smoke
```

## Disposable verification

```powershell
python -B scripts/verify_fullstack.py
```

This is separate from persistent development: it uses fresh tmpfs PostgreSQL at
`127.0.0.1:55434`, generated test credentials, disposable users/polls and isolated
settings. It never reads `.env.local`. See [integration instructions](integration/README.md)
and [QA/release gates](QA.md). The frontend production build is not served by
Django automatically; production static/deployment decisions remain gated.


Production settings and deployment are separate from this local workflow. See
[RELEASE.md](RELEASE.md) and the sanitized .env.production.example. Do not copy
production values into .env.local or run production migration/cutover steps here.
