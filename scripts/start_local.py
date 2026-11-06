"""Start the existing local stack from ignored .env.local; never migrate."""

import argparse
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


class LocalSetupError(RuntimeError):
    pass


def local_environment(path, inherited=None):
    if not path.is_file():
        raise LocalSetupError(
            "Create the Git-ignored .env.local from .env.example."
        )
    values = dotenv_values(path, interpolate=False)
    if values.get("DJANGO_SETTINGS_MODULE") not in (
        None,
        "alx_project_nexus.settings_local",
    ):
        raise LocalSetupError(".env.local must select settings_local.")
    if values.get("NEXUS_PASSWORD_RESET_ENABLED", "false").lower() != "false":
        raise LocalSetupError(
            "This startup command does not enable password recovery."
        )
    env = {
        key: value
        for key, value in (
            os.environ if inherited is None else inherited
        ).items()
        if not key.startswith(("DJANGO_", "NEXUS_", "POSTGRES_"))
        and key not in {"DATABASE_URL", "RENDER", "TESTING"}
    }
    allowed = {"NEXUS_BALLOT_AUTHORITY", "NEXUS_BALLOT_WRITES_ENABLED"}
    env.update(
        {
            key: value
            for key, value in values.items()
            if value is not None
            and (key.startswith("NEXUS_LOCAL_") or key in allowed)
        }
    )
    env.update(
        {
            "DJANGO_SETTINGS_MODULE": "alx_project_nexus.settings_local",
            "NEXUS_PASSWORD_RESET_ENABLED": "false",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
        }
    )
    required = (
        "SECRET_KEY",
        "DB_HOST",
        "DB_PORT",
        "DB_NAME",
        "DB_USER",
        "DB_PASSWORD",
        "ALLOWED_HOSTS",
    )
    missing = [name for name in required if not env.get("NEXUS_LOCAL_" + name)]
    if missing:
        raise LocalSetupError(
            "Missing local variable names: "
            + ", ".join("NEXUS_LOCAL_" + name for name in missing)
        )
    return env


def verify_database(env):
    # Fresh process: select settings before every Django import.
    os.environ.clear()
    os.environ.update(env)
    sys.path.insert(0, str(ROOT))
    import django

    django.setup()
    from django.conf import settings
    from django.db import connection, transaction
    from django.db.migrations.executor import MigrationExecutor

    if (
        not settings.DEBUG
        or settings.SECURE_SSL_REDIRECT
        or settings.NEXUS_REFRESH_COOKIE_SECURE
        or settings.NEXUS_PASSWORD_RESET_ENABLED
        or settings.EMAIL_BACKEND
        != "django.core.mail.backends.locmem.EmailBackend"
    ):
        raise LocalSetupError(
            "Local HTTP/email safety settings are inconsistent."
        )
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute("SELECT current_database(), current_user")
                if cursor.fetchone() != (
                    env["NEXUS_LOCAL_DB_NAME"],
                    env["NEXUS_LOCAL_DB_USER"],
                ):
                    raise LocalSetupError(
                        "The local database identity did not match."
                    )
            executor = MigrationExecutor(connection)
            pending = executor.migration_plan(
                executor.loader.graph.leaf_nodes()
            )
            if pending:
                raise LocalSetupError(
                    "Local migrations are pending. Review them explicitly "
                    "after a backup; startup never runs migrations."
                )
    except LocalSetupError:
        raise
    except Exception:
        raise LocalSetupError(
            "The existing local database could not be verified. "
            "Check the service "
            "and .env.local credentials; no database was created or changed."
        ) from None
    finally:
        connection.close()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def require_free(port):
    # Check both localhost families; never attach to an existing server.
    for family, host in (
        (socket.AF_INET, "127.0.0.1"),
        (socket.AF_INET6, "::1"),
    ):
        with socket.socket(family) as listener:
            try:
                listener.bind((host, port))
            except OSError:
                raise LocalSetupError(
                    f"Port {port} is occupied. Stop that server yourself or "
                    "select a different --api-port/--frontend-port."
                ) from None


def stop_owned(processes):
    for process in reversed(processes):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Read-only config/database verification.",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Start, verify HTTP/proxy, then stop owned servers.",
    )
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--frontend-port", type=int, default=5173)
    args = parser.parse_args()
    if not all(
        1024 <= port <= 65535 for port in (args.api_port, args.frontend_port)
    ):
        raise LocalSetupError("Choose unprivileged local ports (1024..65535).")
    if args.api_port == args.frontend_port:
        raise LocalSetupError("The API and frontend need different ports.")
    env_path = ROOT / ".env.local"
    ignored = subprocess.run(
        ["git", "check-ignore", "--quiet", "--", ".env.local"],
        cwd=ROOT,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if ignored.returncode:
        raise LocalSetupError(".env.local must remain Git-ignored.")
    env = local_environment(env_path)
    verify_database(env)
    print(
        "Local settings and PostgreSQL verified read-only; "
        "no pending migrations.",
        flush=True,
    )
    if args.check:
        return
    require_free(args.api_port)
    require_free(args.frontend_port)
    node = shutil.which("node")
    vite = ROOT / "frontend/node_modules/vite/bin/vite.js"
    if not node or not vite.is_file():
        raise LocalSetupError(
            "Node/Vite is unavailable; run npm ci in frontend first."
        )
    api = f"http://127.0.0.1:{args.api_port}"
    frontend = f"http://localhost:{args.frontend_port}"
    env["NEXUS_PROXY_TARGET"] = api
    processes = []
    with (
        tempfile.TemporaryFile() as api_log,
        tempfile.TemporaryFile() as vite_log,
    ):
        try:
            for command, log, cwd in (
                (
                    [
                        sys.executable,
                        "-B",
                        "manage.py",
                        "runserver",
                        f"127.0.0.1:{args.api_port}",
                        "--noreload",
                    ],
                    api_log,
                    ROOT,
                ),
                (
                    [
                        node,
                        str(vite),
                        "--host",
                        "localhost",
                        "--port",
                        str(args.frontend_port),
                    ],
                    vite_log,
                    ROOT / "frontend",
                ),
            ):
                processes.append(
                    subprocess.Popen(
                        command,
                        cwd=cwd,
                        env=env,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        creationflags=getattr(
                            subprocess, "CREATE_NO_WINDOW", 0
                        ),
                    )
                )
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({}), NoRedirect()
            )
            for _ in range(150):
                if any(process.poll() is not None for process in processes):
                    raise LocalSetupError(
                        "An owned server exited; check local ports "
                        "and dependencies."
                    )
                api_log.seek(0)
                vite_log.seek(0)
                announced = (
                    api.encode() in api_log.read()
                    and frontend.encode() in vite_log.read()
                )
                if announced:
                    try:
                        with opener.open(
                            frontend + "/api/v2/auth/csrf/", timeout=2
                        ) as response:
                            if (
                                response.status == 200
                                and response.headers.get("Location") is None
                            ):
                                break
                    except (urllib.error.URLError, TimeoutError):
                        pass
                time.sleep(0.1)
            else:
                raise LocalSetupError(
                    "Owned local servers/proxy failed readiness."
                )
            print("Frontend: " + frontend + " | API: " + api, flush=True)
            print(
                "Local HTTP proxy verified; persistent database untouched.",
                flush=True,
            )
            if not args.smoke:
                print(
                    "Ctrl+C stops only these servers; "
                    "PostgreSQL stays running.",
                    flush=True,
                )
                while all(process.poll() is None for process in processes):
                    time.sleep(0.5)
                raise LocalSetupError("A local server exited.")
        finally:
            stop_owned(processes)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Owned local servers stopped; PostgreSQL remains unchanged.")
    except LocalSetupError as error:
        print("Local startup stopped: " + str(error), file=sys.stderr)
        sys.exit(1)
