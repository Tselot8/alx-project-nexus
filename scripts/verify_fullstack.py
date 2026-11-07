"""One-command disposable PostgreSQL, Django, Vite and browser verification.

Never reads dotenv files or connects to existing databases. Only a container
created and labelled by this invocation can be removed by its cleanup.
"""

import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def clean_environment():
    return {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("NEXUS_", "POSTGRES_", "DJANGO_"))
        and key not in {"DATABASE_URL", "RENDER", "TESTING"}
    }


def require_free(port):
    try:
        with socket.socket() as listener:
            if os.name == "nt":
                # Keep Windows probes exclusive; never enable SO_REUSEADDR.
                listener.setsockopt(
                    socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1
                )
            else:
                # Match Node/POSIX TIME_WAIT reuse, not SO_REUSEPORT sharing.
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", port))
            listener.listen(1)
    except OSError:
        raise RuntimeError(
            f"Loopback port {port} is occupied; nothing was replaced."
        ) from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--http-only",
        action="store_true",
        help="Explicitly skip browser verification.",
    )
    parser.add_argument(
        "--integration-only",
        action="store_true",
        help="Run live tests without repeating the backend suite.",
    )
    parser.add_argument(
        "--browser-only",
        action="store_true",
        help="Run only real-browser journeys on a fresh stack.",
    )
    parser.add_argument(
        "--backend-tests",
        "--tests",
        dest="backend_tests",
        nargs="+",
        metavar="PATH",
        help="Run selected backend test paths on a fresh isolated database.",
    )
    args = parser.parse_args()
    for target in args.backend_tests or []:
        path = (ROOT / target.split("::", 1)[0]).resolve()
        if (
            not any(
                path.is_relative_to(ROOT / app)
                for app in (
                    "accounts",
                    "polls",
                    "alx_project_nexus",
                    "integration",
                )
            )
            or not path.exists()
        ):
            raise RuntimeError(
                "Backend test paths must exist inside the project."
            )
    env = clean_environment()
    if any(
        os.getenv(key)
        for key in ("DOCKER_HOST", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH")
    ):
        raise RuntimeError("Clear Docker endpoint overrides before running.")
    context = subprocess.check_output(
        ["docker", "context", "show"], text=True
    ).strip()

    def docker(*parts, check=True):
        return subprocess.run(
            ["docker", "--context", context, *parts],
            env=env,
            check=check,
            capture_output=True,
            text=True,
        )

    endpoint = docker(
        "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"
    ).stdout.strip()
    if not (
        endpoint.startswith("npipe:////./pipe/")
        or endpoint.startswith("unix:///")
    ):
        raise RuntimeError(
            "Only a local named-pipe or Unix-socket Docker engine is allowed."
        )
    if docker("info", "--format", "{{.OSType}}").stdout.strip() != "linux":
        raise RuntimeError("Docker Desktop's local Linux engine is required.")
    if not docker(
        "image", "ls", "postgres:15", "--format", "{{.ID}}"
    ).stdout.strip():
        raise RuntimeError(
            "Install postgres:15 explicitly before running. "
            "No image was pulled."
        )
    for port in (55434, 5181):
        require_free(port)
    nonce = secrets.token_hex(6)
    container = "nexus-i-" + nonce
    if docker("container", "inspect", container, check=False).returncode == 0:
        raise RuntimeError(
            "Disposable container name conflicts; nothing was replaced."
        )
    existing_ids = set(docker("ps", "-aq").stdout.split())
    existing_volumes = set(docker("volume", "ls", "-q").stdout.split())
    existing_networks = set(docker("network", "ls", "-q").stdout.split())
    env.update(
        {
            "DJANGO_SETTINGS_MODULE": "alx_project_nexus.settings_test",
            "NEXUS_TEST_SECRET_KEY": secrets.token_urlsafe(64),
            "NEXUS_TEST_DB_HOST": "127.0.0.1",
            "NEXUS_TEST_DB_PORT": "55434",
            "NEXUS_TEST_DB_NAME": "nexus_test_i_" + nonce,
            "NEXUS_TEST_DB_USER": "nexus_test_i_user_" + nonce,
            "NEXUS_TEST_DB_PASSWORD": secrets.token_urlsafe(48),
            "NEXUS_INTEGRATION_RUN": nonce,
            "NEXUS_INTEGRATION_HTTP_ONLY": "1" if args.http_only else "0",
            "NEXUS_BALLOT_AUTHORITY": "bridge",
            "NEXUS_BALLOT_WRITES_ENABLED": "true",
            "NEXUS_PASSWORD_RESET_ENABLED": "false",
            "PYTHONDONTWRITEBYTECODE": "1",
            "DJANGO_LIVE_TEST_SERVER_ADDRESS": "127.0.0.1",
        }
    )
    env.update(
        {
            "POSTGRES_DB": env["NEXUS_TEST_DB_NAME"],
            "POSTGRES_USER": env["NEXUS_TEST_DB_USER"],
            "POSTGRES_PASSWORD": env["NEXUS_TEST_DB_PASSWORD"],
        }
    )

    def run(*command):
        subprocess.run(command, cwd=ROOT, env=env, check=True)

    print(
        "Isolated stack: PostgreSQL 15 / 127.0.0.1:55434 / "
        "temporary memory storage.",
        flush=True,
    )
    print(
        "Django: settings_test, fresh test database; Vite: 127.0.0.1:5181.",
        flush=True,
    )
    frontend_workspace = tempfile.TemporaryDirectory(
        prefix="nexus-i-frontcheck-"
    )
    try:
        frontend = ROOT / "frontend"
        if not (
            args.integration_only or args.browser_only or args.backend_tests
        ):
            frontend = Path(frontend_workspace.name) / "frontend"
            shutil.copytree(
                ROOT / "frontend",
                frontend,
                ignore=shutil.ignore_patterns(
                    "node_modules",
                    "dist",
                    "coverage",
                    ".env*",
                    "test-results",
                    "playwright-report",
                ),
            )
            npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
            if not npm:
                raise RuntimeError(
                    "npm is required for frontend verification."
                )
            subprocess.run([npm, "ci"], cwd=frontend, env=env, check=True)
            subprocess.run(
                [npm, "run", "check"], cwd=frontend, env=env, check=True
            )
        env["NEXUS_INTEGRATION_FRONTEND_DIR"] = str(frontend)
        result = docker(
            "run",
            "--detach",
            "--name",
            container,
            "--label",
            "project-nexus.integration=" + nonce,
            "--publish",
            "127.0.0.1:55434:5432",
            "--tmpfs",
            "/var/lib/postgresql/data:rw",
            "--env",
            "POSTGRES_DB",
            "--env",
            "POSTGRES_USER",
            "--env",
            "POSTGRES_PASSWORD",
            "postgres:15",
            check=False,
        )
        if result.returncode:
            raise RuntimeError(
                "Disposable PostgreSQL startup failed; "
                "existing resources were not replaced."
            )
        info = json.loads(docker("inspect", container).stdout)[0]
        bindings = info["HostConfig"]["PortBindings"]["5432/tcp"]
        if bindings != [{"HostIp": "127.0.0.1", "HostPort": "55434"}]:
            raise RuntimeError("Unexpected database binding.")
        if any(mount["Type"] == "volume" for mount in info["Mounts"]):
            raise RuntimeError(
                "Unexpected persistent volume; refusing database access."
            )
        for _ in range(60):
            ready = docker(
                "exec",
                container,
                "sh",
                "-c",
                'exec pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"',
                check=False,
            )
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("Disposable PostgreSQL did not become ready.")
        run(sys.executable, "-B", "manage.py", "check")
        run(
            sys.executable,
            "-B",
            "manage.py",
            "makemigrations",
            "--check",
            "--dry-run",
        )
        if not (args.integration_only or args.browser_only):
            run(
                sys.executable,
                "-B",
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                "--tb=short",
                "-q",
                *(args.backend_tests or []),
            )
        if args.backend_tests:
            return
        run(
            sys.executable,
            "-B",
            "-m",
            "pytest",
            *(
                [
                    "integration/test_workflows.py"
                    "::test_real_browser_workflows",
                    "integration/test_browser_qa.py",
                ]
                if args.browser_only
                else ["integration"]
            ),
            "-rP",
            "-p",
            "no:cacheprovider",
            "--tb=short",
            "-q",
        )
    finally:
        try:
            frontend_workspace.cleanup()
        finally:
            cleanup_database(
                docker,
                container,
                nonce,
                existing_ids,
                existing_volumes,
                existing_networks,
            )


def cleanup_database(
    docker, container, nonce, existing_ids, existing_volumes, existing_networks
):
    inspected = docker("inspect", container, check=False)
    if inspected.returncode == 0:
        owned = json.loads(inspected.stdout)[0]
        if owned["Config"]["Labels"].get("project-nexus.integration") != nonce:
            raise RuntimeError(
                "Cleanup ownership mismatch; no resource removed."
            )
        docker("rm", "--force", container)
    if not existing_ids.issubset(set(docker("ps", "-aq").stdout.split())):
        raise RuntimeError(
            "An existing container disappeared during verification."
        )
    if set(docker("volume", "ls", "-q").stdout.split()) != existing_volumes:
        raise RuntimeError(
            "Docker volume inventory changed during verification."
        )
    if set(docker("network", "ls", "-q").stdout.split()) != existing_networks:
        raise RuntimeError(
            "Docker network inventory changed during verification."
        )
    print(
        "Owned disposable container removed; "
        "existing resource inventories preserved.",
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        print("Verification stopped: " + str(error), file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError:
        # Child test output has actionable assertions. Never echo environments,
        # Never echo connection strings, cookies, JWTs or exception objects.
        print(
            "Verification failed. "
            "Review the safe preflight/test messages above.",
            file=sys.stderr,
        )
        sys.exit(1)
