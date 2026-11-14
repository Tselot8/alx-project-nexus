"""Offline production checks; never load dotenv or contact services."""

import argparse
import os
from pathlib import Path
import secrets
import socket
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def synthetic_environment():
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("DJANGO_", "POSTGRES_", "NEXUS_"))
        and key not in {"DATABASE_URL", "RENDER", "TESTING"}
    }
    env.update(
        {
            "DJANGO_SETTINGS_MODULE": "alx_project_nexus.settings",
            "DJANGO_SECRET_KEY": secrets.token_urlsafe(64),
            "DJANGO_ALLOWED_HOSTS": "api.example.invalid",
            "DJANGO_PROXY_MODE": "trusted",
            "DJANGO_PROXY_HEADERS_STRIPPED": "true",
            "DJANGO_HSTS_SECONDS": "3600",
            "POSTGRES_DB": "release_configuration_only",
            "POSTGRES_USER": "release_configuration_only",
            "POSTGRES_PASSWORD": secrets.token_urlsafe(32),
            "POSTGRES_HOST": "database.example.invalid",
            "POSTGRES_PORT": "5432",
            "POSTGRES_SSLMODE": "verify-full",
            "NEXUS_PASSWORD_RESET_ENABLED": "false",
            "NEXUS_BALLOT_WRITES_ENABLED": "false",
            "NEXUS_BALLOT_AUTHORITY": "bridge",
        }
    )
    return env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend-dist", type=Path)
    args = parser.parse_args()
    env = synthetic_environment()
    os.environ.clear()
    os.environ.update(env)
    sys.path.insert(0, str(ROOT))
    import dotenv

    dotenv.load_dotenv = lambda *args, **kwargs: False

    def forbidden(*args, **kwargs):
        raise RuntimeError("Offline release checks cannot access services.")

    socket.create_connection = forbidden
    socket.socket.connect = forbidden
    socket.socket.connect_ex = forbidden
    import django

    if django.VERSION[:3] < (5, 2, 18):
        raise RuntimeError("The reviewed Django security patch is required.")
    from django.db.backends.base.base import BaseDatabaseWrapper

    BaseDatabaseWrapper.connect = forbidden
    django.setup()
    from django.core.management import call_command

    call_command("check", deploy=True, fail_level="ERROR")
    # Candidate intentionally scopes HSTS to this host; no preload/subdomains.
    # These two warnings require the same explicit review in the real runbook.
    call_command(
        "release_preflight",
        production=True,
        acknowledge_warning=["security.W005", "security.W021"],
    )
    from django.test import Client, override_settings

    with tempfile.TemporaryDirectory(prefix="nexus-k-static-") as directory:
        with override_settings(STATIC_ROOT=directory):
            call_command("collectstatic", interactive=False, verbosity=0)
        for name in (
            "admin/css/base.css",
            "rest_framework/css/bootstrap.min.css",
        ):
            if not (Path(directory) / name).is_file():
                raise RuntimeError("Expected static assets are missing.")
        if args.frontend_dist:
            from alx_project_nexus.deployment import validate_artifact

            root = args.frontend_dist.resolve()
            validate_artifact(root)
            with override_settings(
                STATIC_ROOT=directory,
                NEXUS_SERVE_FRONTEND=True,
                NEXUS_FRONTEND_DIST=root,
            ):
                verify_serving(Client)
    print("Temporary production static collection verified.")
    print(
        "Synthetic production checks passed; "
        "real release approval remains required."
    )


def verify_serving(client_type):
    """Exercise production middleware without network/database access."""
    import re
    from django.conf import settings

    client = client_type(enforce_csrf_checks=True)
    host = "api.example.invalid"
    response = client.get("/polls", secure=True, HTTP_HOST=host)
    assert response.status_code == 200
    body = b"".join(response.streaming_content)
    response.close()
    assert b'id="root"' in body
    assert response["Cache-Control"] == "private, no-store"
    assets = set(re.findall(rb'["\\\'](/assets/[^"\\\']+)["\\\']', body))
    assert assets, "Built frontend has no local assets."
    for path in assets:
        response = client.get(path.decode(), secure=True, HTTP_HOST=host)
        assert response.status_code == 200
        assert b"".join(response.streaming_content)
        response.close()
    response = client.get(
        "/static/admin/css/base.css",
        secure=True,
        HTTP_HOST=host,
    )
    assert response.status_code == 200
    assert b"".join(response.streaming_content)
    response.close()
    assert (
        client.get(
            "/api/v2/missing/",
            secure=True,
            HTTP_HOST=host,
        ).status_code
        == 404
    )
    assert client.get(
        "/health/live/",
        secure=True,
        HTTP_HOST=host,
    ).json() == {"status": "ok"}
    csrf = client.get(
        "/api/v2/auth/csrf/",
        secure=True,
        HTTP_HOST=host,
    ).json()["csrf_token"]
    assert client.cookies["csrftoken"]["secure"]
    assert (
        client.post(
            "/api/v2/auth/refresh/",
            secure=True,
            HTTP_HOST=host,
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v2/auth/refresh/",
            secure=True,
            HTTP_HOST=host,
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_ORIGIN="https://untrusted.invalid",
        ).status_code
        == 403
    )
    # Valid CSRF reaches the no-session 401, rather than a CSRF failure.
    assert (
        client.post(
            "/api/v2/auth/refresh/",
            secure=True,
            HTTP_HOST=host,
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_ORIGIN="https://" + host,
        ).status_code
        == 401
    )
    # The initial public staging artifact must reject signup without DB I/O.
    assert not settings.NEXUS_REGISTRATION_ENABLED
    for path in ("/api/accounts/register/", "/api/v2/auth/register/"):
        assert client.post(
            path,
            secure=True,
            HTTP_HOST=host,
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_ORIGIN="https://" + host,
        ).status_code == 503
    assert settings.NEXUS_REFRESH_COOKIE_SECURE
    assert not settings.NEXUS_PASSWORD_RESET_ENABLED
    assert not settings.NEXUS_BALLOT_WRITES_ENABLED
    print("Production artifact/API routing, Secure cookies and CSRF verified.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Never emit settings, DSNs, exception payloads or credentials.
        print(
            "Offline release checks failed; run focused configuration tests.",
            file=sys.stderr,
        )
        sys.exit(1)
