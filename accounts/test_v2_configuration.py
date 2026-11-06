"""Production recovery and cookie defaults without database or SMTP access."""

import json
import os
import subprocess
import sys
import unittest


TRUSTED_ORIGIN = "https://frontend.example.invalid"


class AccountConfigurationTests(unittest.TestCase):
    def probe(self, overrides=None):
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("DJANGO_", "NEXUS_", "POSTGRES_"))
            and key not in {"DATABASE_URL", "PYTHONPATH"}
        }
        env.update(
            {
                "DJANGO_SETTINGS_MODULE": "alx_project_nexus.settings",
                "DJANGO_SECRET_KEY": "non-secret-configuration-probe-" * 4,
                "DJANGO_ALLOWED_HOSTS": "api.example.invalid",
                "DJANGO_PROXY_MODE": "direct",
                "POSTGRES_HOST": "database.example.invalid",
                "POSTGRES_PORT": "5432",
                "POSTGRES_DB": "fixture",
                "POSTGRES_USER": "fixture",
                "POSTGRES_PASSWORD": "fixture-only",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONPATH": os.getcwd(),
            }
        )
        env.update(overrides or {})
        code = """
import json
import socket
import dotenv
dotenv.load_dotenv = lambda *a, **kw: False
def deny(*args, **kwargs):
    raise AssertionError("Configuration probes cannot use network services.")
socket.socket.connect = deny
socket.create_connection = deny
from django.core.exceptions import ImproperlyConfigured
try:
    from django.conf import settings
    print(json.dumps({
        "secure": settings.NEXUS_REFRESH_COOKIE_SECURE,
        "enabled": settings.NEXUS_PASSWORD_RESET_ENABLED,
        "origin": settings.NEXUS_PASSWORD_RESET_ORIGIN,
        "cors": settings.CORS_ALLOW_ALL_ORIGINS,
        "credentials": settings.CORS_ALLOW_CREDENTIALS
            if hasattr(settings, "CORS_ALLOW_CREDENTIALS") else False,
    }))
except ImproperlyConfigured:
    print(json.dumps({"rejected": True}))
"""
        result = subprocess.run(
            [sys.executable, "-B", "-c", code],
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_default_production_cookies_secure_and_recovery_disabled(self):
        result = self.probe({"DJANGO_DEBUG": "True"})
        self.assertTrue(result["secure"])
        self.assertFalse(result["enabled"])
        self.assertFalse(result["cors"])
        self.assertFalse(result["credentials"])

    def test_enabled_recovery_rejects_missing_origin_or_smtp(self):
        for overrides in (
            {},
            {"NEXUS_PASSWORD_RESET_FRONTEND_ORIGIN": TRUSTED_ORIGIN},
        ):
            result = self.probe(
                {"NEXUS_PASSWORD_RESET_ENABLED": "true", **overrides}
            )
            self.assertTrue(result["rejected"])

    def test_production_reset_origin_rejects_unsafe_destinations(self):
        for origin in (
            "http://frontend.example.invalid",
            "https://frontend.example.invalid/untrusted-path",
            "https://name:password@frontend.example.invalid",
            "https://*.example.invalid",
        ):
            self.assertTrue(
                self.probe(
                    {
                        "NEXUS_PASSWORD_RESET_ENABLED": "true",
                        "NEXUS_PASSWORD_RESET_FRONTEND_ORIGIN": origin,
                    }
                )["rejected"]
            )

    def test_explicit_safe_configuration_needs_no_network_to_load(self):
        result = self.probe(
            {
                "NEXUS_PASSWORD_RESET_ENABLED": "true",
                "NEXUS_PASSWORD_RESET_FRONTEND_ORIGIN": TRUSTED_ORIGIN,
                "NEXUS_EMAIL_HOST": "mail.example.invalid",
                "NEXUS_PASSWORD_RESET_APPROVED": "true",
                "NEXUS_DEFAULT_FROM_EMAIL": "noreply@example.invalid",
            }
        )
        self.assertTrue(result["enabled"])
        self.assertTrue(result["secure"])
        self.assertEqual(result["origin"], TRUSTED_ORIGIN)
