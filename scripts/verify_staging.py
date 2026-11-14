"""Build and smoke a production artifact on local Docker, without a database.

No cloud access, published ports, migrations, email, backfill or voting writes.
Only the nonce-labelled container and image created here may be removed.
"""

import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    from scripts.check_release import synthetic_environment

    if any(
        os.getenv(key)
        for key in (
            "DOCKER_HOST",
            "DOCKER_TLS_VERIFY",
            "DOCKER_CERT_PATH",
        )
    ):
        raise RuntimeError("Clear Docker endpoint overrides first.")
    env = synthetic_environment()
    context = subprocess.check_output(
        ["docker", "context", "show"],
        text=True,
        encoding="utf-8",
        errors="replace",
    ).strip()

    def docker(*args, check=True, capture=True):
        return subprocess.run(
            ["docker", "--context", context, *args],
            cwd=ROOT,
            env=env,
            check=check,
            capture_output=capture,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    endpoint = docker(
        "context",
        "inspect",
        "--format",
        "{{.Endpoints.docker.Host}}",
    ).stdout.strip()
    if not endpoint.startswith(("npipe:////./pipe/", "unix:///")):
        raise RuntimeError("Only the local Docker engine is allowed.")
    if docker("info", "--format", "{{.OSType}}").stdout.strip() != "linux":
        raise RuntimeError("The local Linux engine is required.")
    nonce = secrets.token_hex(6)
    name = "nexus-l-" + nonce
    image = "nexus-staging-check:" + nonce
    label = "project-nexus.staging-check"
    for kind, target in (
        ("container", name),
        ("container", name + "-offline"),
        ("image", image),
    ):
        if docker(kind, "inspect", target, check=False).returncode == 0:
            raise RuntimeError("Resource collision; nothing replaced.")
    try:
        print(
            "Building local staging artifact (public dependencies).",
            flush=True,
        )
        built = docker(
            "build",
            "--label",
            label + "=" + nonce,
            "--file",
            "Dockerfile.staging",
            "--tag",
            image,
            ".",
            check=False,
        )
        if built.returncode:
            output = built.stdout + built.stderr
            if any(
                marker in output
                for marker in (
                    "ReadTimeout",
                    "TLS handshake timeout",
                    "EAI_AGAIN",
                    "ETIMEDOUT",
                    "ENOTFOUND",
                    "network is unreachable",
                )
            ):
                print("Public dependency download timed out/unavailable.")
            else:
                print("Artifact build failed; verify focused build checks.")
            # Registry/build errors may embed signed download URLs.
            # Do not print or persist raw Docker/pip output.
            raise RuntimeError("Local artifact build failed.")
        # Run the actual image's production settings, static and API routing.
        docker(
            "run",
            "--name",
            name + "-offline",
            "--label",
            label + "=" + nonce,
            "--network",
            "none",
            image,
            "python",
            "-B",
            "scripts/check_release.py",
            "--frontend-dist",
            "/app/frontend/dist",
            capture=False,
        )
        settings_env = {
            key: value
            for key, value in env.items()
            if key.startswith(("DJANGO_", "POSTGRES_", "NEXUS_"))
        }
        settings_env["NEXUS_SERVE_FRONTEND"] = "true"
        settings_env["PORT"] = "10000"
        # Values travel via inherited environment names, not command arguments.
        run_env = {**env, **settings_env}
        args = [
            "docker",
            "--context",
            context,
            "run",
            "--detach",
            "--network",
            "none",
            "--memory",
            "512000000",
            "--memory-swap",
            "512000000",
            "--cpus",
            "0.1",
            "--name",
            name,
            "--label",
            label + "=" + nonce,
        ]
        for key in settings_env:
            args.extend(("--env", key))
        subprocess.run(
            [*args, image],
            cwd=ROOT,
            env=run_env,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        probe = r"""
import json
import ssl
import urllib.error
import urllib.request
context = ssl.create_default_context(
    cafile="/etc/ssl/certs/ca-certificates.crt"
)
assert context.get_ca_certs()
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
def get(path, expected, kind):
    req = urllib.request.Request("http://127.0.0.1:10000" + path, headers={
        "Host": "api.example.invalid", "X-Forwarded-Proto": "https",
    })
    try:
        res = opener.open(req, timeout=8)
    except urllib.error.HTTPError as error:
        res = error
    assert res.code == expected
    body = res.read()
    if kind == "json":
        assert res.headers["Content-Type"].startswith("application/json")
        return json.loads(body)
    assert b'id="root"' in body
assert get("/health/live/", 200, "json") == {"status": "ok"}
assert get("/health/ready/", 503, "json") == {"status": "unavailable"}
get("/polls", 200, "html")
get("/api/v2/auth/csrf/", 200, "json")
# Malformed HTTP must not place its private-looking URL in Gunicorn logs.
import socket
with socket.create_connection(("127.0.0.1", 10000), timeout=3) as client:
    client.sendall(b"GET /?share=nexus-log-canary HTTP/9.9\r\n\r\n")
    client.recv(1024)
"""
        for _ in range(30):
            result = docker(
                "exec",
                name,
                "python",
                "-B",
                "-c",
                probe,
                check=False,
            )
            if result.returncode == 0:
                break
            if (
                docker(
                    "inspect", "-f", "{{.State.Running}}", name
                ).stdout.strip()
                != "true"
            ):
                raise RuntimeError("Owned Gunicorn process exited.")
            time.sleep(1)
        else:
            raise RuntimeError("Owned Gunicorn health/artifact smoke failed.")
        logs = docker("logs", name)
        if "nexus-log-canary" in logs.stdout + logs.stderr:
            raise RuntimeError("Private-looking URL reached server logs.")
        info = json.loads(docker("inspect", name).stdout)[0]
        assert info["Config"]["User"] == "10001:10001"
        assert info["HostConfig"]["Memory"] == 512000000
        assert info["HostConfig"]["MemorySwap"] == 512000000
        assert info["HostConfig"]["NanoCpus"] == 100000000
        assert not info["State"]["OOMKilled"]
        print(
            "Render-size smoke: 512 MB, no extra swap, 0.1 CPU, PORT=10000; "
            "non-root, no OOM. Debian CA bundle loads; remote TLS unverified."
        )
        print("Local non-root Gunicorn artifact and static/API smoke passed.")
        print("No staging environment deployed; database readiness is 503.")
    finally:
        for target in (name, name + "-offline"):
            info = docker("container", "inspect", target, check=False)
            if info.returncode == 0:
                data = json.loads(info.stdout)[0]
                if data["Config"]["Labels"].get(label) != nonce:
                    raise RuntimeError(
                        "Container ownership mismatch; not removed."
                    )
                docker("rm", "--force", target)
        info = docker("image", "inspect", image, check=False)
        if info.returncode == 0:
            data = json.loads(info.stdout)[0]
            if data["Config"]["Labels"].get(label) != nonce:
                raise RuntimeError("Image ownership mismatch; not removed.")
            docker("image", "rm", image)
        print(
            "Owned staging-check resources cleaned; existing data untouched."
        )


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    try:
        main()
    except Exception:
        # No raw process exceptions, environment, request bodies or DB errors.
        print("Local staging artifact verification failed.", file=sys.stderr)
        sys.exit(1)
