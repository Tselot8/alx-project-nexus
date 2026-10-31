"""PostgreSQL-only tests; no dotenv files or production credential fallback."""

import os

from django.core.exceptions import ImproperlyConfigured

if os.getenv("DJANGO_SETTINGS_MODULE") != __name__:
    raise ImproperlyConfigured("Select settings_test explicitly.")

from .settings import *  # noqa: E402,F401,F403
from .settings import _isolated_database, _required  # noqa: E402

SECRET_KEY = _required("NEXUS_TEST_SECRET_KEY")
DEBUG = False
DATABASES = _isolated_database("NEXUS_TEST", "nexus_test")
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1", "[::1]"]
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = []
CSRF_TRUSTED_ORIGINS = []
SECURE_SSL_REDIRECT = False
CSRF_COOKIE_SECURE = False
SESSION_COOKIE_SECURE = False
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "nexus-tests",
        "KEY_PREFIX": "nexus-tests",
    }
}

NEXUS_REFRESH_COOKIE_SECURE = False
