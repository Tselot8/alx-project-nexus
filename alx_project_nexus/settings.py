"""Shared configuration and the existing production settings entry point."""

import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

from .production import hostname, production_settings, smtp_settings

BASE_DIR = Path(__file__).resolve().parent.parent
_ISOLATED_MODULES = {
    "alx_project_nexus.settings_local",
    "alx_project_nexus.settings_test",
}
_ISOLATED = os.getenv("DJANGO_SETTINGS_MODULE") in _ISOLATED_MODULES

# Preserve production dotenv behavior. Local/test modules never read this file.
if not _ISOLATED:
    load_dotenv(BASE_DIR / ".env")


def _required(name):
    value = os.getenv(name)
    if value is None or not value.strip():
        raise ImproperlyConfigured(f"{name} is required.")
    return value


def _hosts(name, default=None, loopback_only=False):
    raw = _required(name) if default is None else os.getenv(name, default)
    values = [value.strip() for value in raw.split(",") if value.strip()]
    local = {"localhost", "127.0.0.1", "[::1]"}
    if not values or any(
        "*" in value or "/" in value or "://" in value for value in values
    ):
        raise ImproperlyConfigured(f"{name} requires explicit allowed hosts.")
    if loopback_only and any(value not in local for value in values):
        raise ImproperlyConfigured(f"{name} permits only loopback hosts.")
    return values


def _origins(name, loopback_only=False):
    values = [
        value.strip()
        for value in os.getenv(name, "").split(",")
        if value.strip()
    ]
    result = []
    for value in values:
        try:
            parsed = urlsplit(value)
            port = parsed.port
            valid = (
                parsed.scheme
                in ({"http", "https"} if loopback_only else {"https"})
                and parsed.hostname
                and (
                    loopback_only
                    or hostname(
                        "[" + parsed.hostname + "]"
                        if ":" in parsed.hostname
                        else parsed.hostname
                    )
                )
                and not parsed.username
                and not parsed.password
                and not parsed.query
                and not parsed.fragment
                and parsed.path in {"", "/"}
                and "*" not in value
                and (port is None or 1 <= port <= 65535)
            )
            if loopback_only:
                valid = valid and parsed.hostname in {
                    "localhost",
                    "127.0.0.1",
                    "::1",
                }
            if not valid:
                raise ValueError
        except ValueError:
            raise ImproperlyConfigured(
                f"{name} requires explicit "
                + (
                    "loopback HTTP(S) origins."
                    if loopback_only
                    else "HTTPS origins."
                )
            ) from None
        result.append(value.rstrip("/"))
    return result


def _isolated_database(prefix, namespace):
    """Never read POSTGRES_* or DATABASE_URL in an isolated profile."""
    host = _required(f"{prefix}_DB_HOST").strip()
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ImproperlyConfigured(
            f"{prefix}_DB_HOST must be a loopback address."
        )
    name = _required(f"{prefix}_DB_NAME").strip()
    user = _required(f"{prefix}_DB_USER").strip()
    pattern = rf"{namespace}_[a-z0-9_]+"
    if not re.fullmatch(pattern, name) or len(name) > 58:
        raise ImproperlyConfigured(
            f"{prefix}_DB_NAME requires the {namespace}_ namespace."
        )
    if not re.fullmatch(pattern, user) or len(user) > 63:
        raise ImproperlyConfigured(
            f"{prefix}_DB_USER requires the {namespace}_ namespace."
        )
    try:
        port = int(_required(f"{prefix}_DB_PORT"))
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        raise ImproperlyConfigured(
            f"{prefix}_DB_PORT must be a valid TCP port."
        ) from None
    return {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": name,
            "USER": user,
            "PASSWORD": _required(f"{prefix}_DB_PASSWORD"),
            "HOST": host,
            "PORT": str(port),
            "CONN_MAX_AGE": 0,
            "OPTIONS": {"connect_timeout": 5},
            "TEST": {"NAME": f"test_{name}"},
        }
    }


DEBUG = False
if _ISOLATED:
    # Unusable until the explicitly selected module supplies its own settings.
    SECRET_KEY = ""
    ALLOWED_HOSTS = []
    DATABASES = {}
    CORS_ALLOWED_ORIGINS = []
    CSRF_TRUSTED_ORIGINS = []
else:
    globals().update(production_settings(os.environ))
    CORS_ALLOWED_ORIGINS = _origins("DJANGO_CORS_ALLOWED_ORIGINS")
    CSRF_TRUSTED_ORIGINS = _origins("DJANGO_CSRF_TRUSTED_ORIGINS")

CORS_ALLOW_ALL_ORIGINS = False

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "drf_yasg",
    "polls.apps.PollsConfig",
    "accounts",
]

AUTH_USER_MODEL = "accounts.User"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "alx_project_nexus.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]
WSGI_APPLICATION = "alx_project_nexus.wsgi.application"

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation."
        "UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "CommonPasswordValidator"
        )
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "NumericPasswordValidator"
        )
    },
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "accounts.authentication.VersionedJWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticatedOrReadOnly",
    ),
    "DEFAULT_PAGINATION_CLASS": (
        "rest_framework.pagination.PageNumberPagination"
    ),
    "PAGE_SIZE": 10,
}
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "unique-snowflake",
    }
}

# Only an explicitly selected development/test module can disable these.
SECURE_SSL_REDIRECT = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True

# V2 cookie sessions keep the legacy JWT lifetimes and JSON routes unchanged.
INSTALLED_APPS += ["rest_framework_simplejwt.token_blacklist"]
NEXUS_REFRESH_COOKIE_SECURE = True  # Explicit local/test overrides only.
PASSWORD_RESET_TIMEOUT = 1800
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {
    "v2_auth": "30/min",
    "v2_login": "10/min",
    "v2_account": "120/min",
    "v2_recovery": "5/hour",
}


def _account_email_settings():
    enabled = os.getenv("NEXUS_PASSWORD_RESET_ENABLED", "false").lower()
    if enabled not in {"true", "false"}:
        raise ImproperlyConfigured(
            "NEXUS_PASSWORD_RESET_ENABLED must be true or false."
        )
    origins = _origins(
        "NEXUS_PASSWORD_RESET_FRONTEND_ORIGIN", loopback_only=_ISOLATED
    )
    if len(origins) > 1 or (enabled == "true" and not origins):
        raise ImproperlyConfigured(
            "Password recovery requires one trusted frontend origin."
        )
    return {
        "NEXUS_PASSWORD_RESET_ENABLED": enabled == "true",
        "NEXUS_PASSWORD_RESET_ORIGIN": origins[0] if origins else "",
        **smtp_settings(os.environ, enabled == "true", _ISOLATED),
    }


globals().update(_account_email_settings())

# Capability headers must never appear in Django exception reports.
DEFAULT_EXCEPTION_REPORTER_FILTER = (
    "polls.exception_filter.ShareAwareExceptionReporterFilter"
)


# F: explicit, fail-closed voting-store rollout. Enabling writes is an
# operator assertion that ALL old Vote writers (including workers) are drained.
# Do not enable ballot-only reads until backfill_ballots --reconcile succeeds.
def _ballot_settings():
    mode = os.getenv("NEXUS_BALLOT_AUTHORITY", "bridge")
    enabled = os.getenv(
        "NEXUS_BALLOT_WRITES_ENABLED", "true" if _ISOLATED else "false"
    ).lower()
    if mode not in {"bridge", "ballots"} or enabled not in {"true", "false"}:
        raise ImproperlyConfigured("Invalid ballot rollout configuration.")
    return {
        "NEXUS_BALLOT_AUTHORITY": mode,
        "NEXUS_BALLOT_WRITES_ENABLED": enabled == "true",
    }


globals().update(_ballot_settings())
