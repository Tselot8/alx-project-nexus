"""Fail-closed production configuration; no network, database or dotenv I/O."""

import ipaddress
import re

from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.validators import validate_email


def required(env, name):
    value = env.get(name, "")
    if not value.strip():
        raise ImproperlyConfigured(f"{name} is required.")
    return value


def integer(env, name, default, minimum, maximum):
    try:
        value = int(env.get(name, str(default)))
        if not minimum <= value <= maximum:
            raise ValueError
        return value
    except ValueError:
        raise ImproperlyConfigured(
            f"{name} is outside its allowed range."
        ) from None


def hostname(value):
    if value.startswith("[") and value.endswith("]"):
        try:
            return ipaddress.ip_address(value[1:-1]).version == 6
        except ValueError:
            return False
    return len(value) <= 253 and bool(
        re.fullmatch(
            r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
            r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*",
            value,
        )
    )


def production_settings(env):
    secret = required(env, "DJANGO_SECRET_KEY")
    if (
        len(secret) < 50
        or len(set(secret)) < 5
        or secret.startswith("django-insecure-")
    ):
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY requires a strong random value."
        )
    hosts = [
        v.strip() for v in required(env, "DJANGO_ALLOWED_HOSTS").split(",")
    ]
    if not all(hostname(host) for host in hosts):
        raise ImproperlyConfigured(
            "DJANGO_ALLOWED_HOSTS requires explicit valid hosts."
        )
    database = {
        key: required(env, "POSTGRES_" + key)
        for key in ("DB", "USER", "PASSWORD", "HOST", "PORT")
    }
    host = database["HOST"]
    if not hostname(host) and not (
        host.startswith("/") and not any(c.isspace() for c in host)
    ):
        raise ImproperlyConfigured(
            "POSTGRES_HOST must be a hostname or socket path."
        )
    port = integer(env, "POSTGRES_PORT", 5432, 1, 65535)
    sslmode = env.get("POSTGRES_SSLMODE", "verify-full")
    if sslmode not in {"require", "verify-ca", "verify-full", "disable"}:
        raise ImproperlyConfigured("POSTGRES_SSLMODE is invalid.")
    if (
        sslmode == "disable"
        and host not in {"localhost", "127.0.0.1", "[::1]"}
        and not host.startswith("/")
    ):
        raise ImproperlyConfigured("Remote PostgreSQL requires TLS.")
    options = {"connect_timeout": 5, "sslmode": sslmode}
    if env.get("POSTGRES_SSLROOTCERT"):
        options["sslrootcert"] = env["POSTGRES_SSLROOTCERT"]
    proxy = required(env, "DJANGO_PROXY_MODE")
    if proxy not in {"direct", "trusted"}:
        raise ImproperlyConfigured(
            "DJANGO_PROXY_MODE must be direct or trusted."
        )
    if (
        proxy == "trusted"
        and env.get("DJANGO_PROXY_HEADERS_STRIPPED") != "true"
    ):
        raise ImproperlyConfigured(
            "Trusted proxy requires DJANGO_PROXY_HEADERS_STRIPPED=true."
        )
    return {
        "SECRET_KEY": secret,
        "ALLOWED_HOSTS": hosts,
        "DATABASES": {
            "default": {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": database["DB"],
                "USER": database["USER"],
                "PASSWORD": database["PASSWORD"],
                "HOST": host,
                "PORT": str(port),
                "OPTIONS": options,
                "CONN_MAX_AGE": 0,
            }
        },
        "SECURE_PROXY_SSL_HEADER": (
            ("HTTP_X_FORWARDED_PROTO", "https") if proxy == "trusted" else None
        ),
        "USE_X_FORWARDED_HOST": False,
        "USE_X_FORWARDED_PORT": False,
        "SECURE_HSTS_SECONDS": integer(
            env, "DJANGO_HSTS_SECONDS", 0, 0, 31536000
        ),
        "SECURE_HSTS_INCLUDE_SUBDOMAINS": False,
        "SECURE_HSTS_PRELOAD": False,
    }


def smtp_settings(env, enabled, isolated):
    host = env.get("NEXUS_EMAIL_HOST", "")
    sender = env.get("NEXUS_DEFAULT_FROM_EMAIL", "")
    user = env.get("NEXUS_EMAIL_HOST_USER", "")
    password = env.get("NEXUS_EMAIL_HOST_PASSWORD", "")
    mode = env.get("NEXUS_EMAIL_SECURITY", "starttls")
    if mode not in {"starttls", "ssl"}:
        raise ImproperlyConfigured(
            "NEXUS_EMAIL_SECURITY must be starttls or ssl."
        )
    port = integer(
        env, "NEXUS_EMAIL_PORT", 465 if mode == "ssl" else 587, 1, 65535
    )
    timeout = integer(env, "NEXUS_EMAIL_TIMEOUT", 10, 1, 60)
    if enabled and not isolated:
        if env.get("NEXUS_PASSWORD_RESET_APPROVED") != "true":
            raise ImproperlyConfigured(
                "Password recovery requires "
                "NEXUS_PASSWORD_RESET_APPROVED=true."
            )
        try:
            validate_email(sender)
        except ValidationError:
            raise ImproperlyConfigured(
                "NEXUS_DEFAULT_FROM_EMAIL must be a valid sender address."
            ) from None
        if not hostname(host) or bool(user) != bool(password):
            raise ImproperlyConfigured(
                "Password recovery requires valid paired SMTP configuration."
            )
    return {
        "EMAIL_BACKEND": (
            "django.core.mail.backends.locmem.EmailBackend"
            if isolated
            else "django.core.mail.backends.smtp.EmailBackend"
        ),
        "EMAIL_HOST": host,
        "EMAIL_PORT": port,
        "EMAIL_USE_TLS": mode == "starttls",
        "EMAIL_USE_SSL": mode == "ssl",
        "EMAIL_TIMEOUT": timeout,
        "EMAIL_HOST_USER": user,
        "EMAIL_HOST_PASSWORD": password,
        "DEFAULT_FROM_EMAIL": sender,
    }
