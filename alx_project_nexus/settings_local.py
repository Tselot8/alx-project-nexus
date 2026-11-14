"""Local settings, selected explicitly through DJANGO_SETTINGS_MODULE."""

import os

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

if os.getenv("DJANGO_SETTINGS_MODULE") != __name__:
    raise ImproperlyConfigured("Select settings_local explicitly.")

from .settings import *  # noqa: E402,F401,F403
from .settings import (  # noqa: E402
    BASE_DIR,
    _account_email_settings,
    _ballot_settings,
    _hosts,
    _isolated_database,
    _origins,
    _registration_settings,
    _required,
)

# Never load the production .env, and never override explicit shell variables.
load_dotenv(BASE_DIR / ".env.local", override=False)

SECRET_KEY = _required("NEXUS_LOCAL_SECRET_KEY")
DEBUG = True
DATABASES = _isolated_database("NEXUS_LOCAL", "nexus_local")
ALLOWED_HOSTS = _hosts("NEXUS_LOCAL_ALLOWED_HOSTS", loopback_only=True)
CORS_ALLOWED_ORIGINS = _origins(
    "NEXUS_LOCAL_CORS_ALLOWED_ORIGINS", loopback_only=True
)
CSRF_TRUSTED_ORIGINS = _origins(
    "NEXUS_LOCAL_CSRF_TRUSTED_ORIGINS", loopback_only=True
)
CORS_ALLOW_ALL_ORIGINS = False
SECURE_SSL_REDIRECT = False
CSRF_COOKIE_SECURE = False
SESSION_COOKIE_SECURE = False
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "nexus-local",
        "KEY_PREFIX": "nexus-local",
    }
}

# Re-read registration and email configuration after the isolated dotenv load.
globals().update(_registration_settings())
globals().update(_account_email_settings())
NEXUS_REFRESH_COOKIE_SECURE = False

# Re-read isolated rollout settings after .env.local.
globals().update(_ballot_settings())
