"""Offline production checks; never load dotenv or contact services."""

import os
from pathlib import Path
import secrets
import socket
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
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
    from django.test import override_settings

    with tempfile.TemporaryDirectory(prefix="nexus-k-static-") as directory:
        with override_settings(STATIC_ROOT=directory):
            call_command("collectstatic", interactive=False, verbosity=0)
        for name in (
            "admin/css/base.css",
            "rest_framework/css/bootstrap.min.css",
        ):
            if not (Path(directory) / name).is_file():
                raise RuntimeError("Expected static assets are missing.")
    print("Temporary production static collection verified.")
    print(
        "Synthetic production checks passed; "
        "real release approval remains required."
    )


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
