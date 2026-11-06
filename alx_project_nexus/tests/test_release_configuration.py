"""Production validation is deterministic and never contacts services."""

import copy
import unittest

from django.core.exceptions import ImproperlyConfigured

from alx_project_nexus.production import production_settings, smtp_settings
from scripts.audit_secrets import classify, findings


class ProductionConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.env = {
            "DJANGO_SECRET_KEY": "synthetic-configuration-candidate-" * 3,
            "DJANGO_ALLOWED_HOSTS": "api.example.invalid",
            "DJANGO_PROXY_MODE": "direct",
            "POSTGRES_DB": "candidate",
            "POSTGRES_USER": "candidate",
            "POSTGRES_PASSWORD": "fixture-only-candidate",
            "POSTGRES_HOST": "database.example.invalid",
            "POSTGRES_PORT": "5432",
        }

    def test_every_required_production_value_fails_closed_without_echo(self):
        for key in self.env:
            env = copy.copy(self.env)
            del env[key]
            with self.subTest(key=key), self.assertRaises(
                ImproperlyConfigured
            ) as error:
                production_settings(env)
            self.assertIn(key, str(error.exception))
            self.assertNotIn(
                self.env["POSTGRES_PASSWORD"], str(error.exception)
            )

    def test_hostnames_cannot_be_wildcards_origins_ports_or_header_injection(
        self,
    ):
        for value in (
            "*",
            ".example.invalid",
            "https://api.example.invalid",
            "bad host",
            "api.example.invalid:443",
            "api.example.invalid\r\nBad: value",
            "api.example.invalid,",
        ):
            with self.subTest(value=value), self.assertRaises(
                ImproperlyConfigured
            ):
                production_settings(
                    {**self.env, "DJANGO_ALLOWED_HOSTS": value}
                )

    def test_weak_secret_and_database_ports_are_rejected(self):
        for key, values in (
            (
                "DJANGO_SECRET_KEY",
                ["weak", "a" * 64, "django-insecure-" + "candidate" * 9],
            ),
            ("POSTGRES_PORT", ["0", "65536", "not-a-port"]),
        ):
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(
                    ImproperlyConfigured
                ):
                    production_settings({**self.env, key: value})

    def test_proxy_headers_require_explicit_trust_acknowledgement(self):
        self.assertIsNone(
            production_settings(self.env)["SECURE_PROXY_SSL_HEADER"]
        )
        with self.assertRaises(ImproperlyConfigured):
            production_settings({**self.env, "DJANGO_PROXY_MODE": "trusted"})
        config = production_settings(
            {
                **self.env,
                "DJANGO_PROXY_MODE": "trusted",
                "DJANGO_PROXY_HEADERS_STRIPPED": "true",
            }
        )
        self.assertEqual(
            config["SECURE_PROXY_SSL_HEADER"],
            ("HTTP_X_FORWARDED_PROTO", "https"),
        )
        self.assertFalse(config["USE_X_FORWARDED_HOST"])
        self.assertFalse(config["USE_X_FORWARDED_PORT"])
        self.assertEqual(config["SECURE_HSTS_SECONDS"], 0)
        self.assertFalse(config["SECURE_HSTS_PRELOAD"])
        self.assertFalse(config["SECURE_HSTS_INCLUDE_SUBDOMAINS"])

    def test_remote_database_cannot_disable_tls(self):
        with self.assertRaises(ImproperlyConfigured):
            production_settings({**self.env, "POSTGRES_SSLMODE": "disable"})
        self.assertEqual(
            production_settings(self.env)["DATABASES"]["default"]["OPTIONS"][
                "sslmode"
            ],
            "verify-full",
        )
        local = production_settings(
            {
                **self.env,
                "POSTGRES_HOST": "127.0.0.1",
                "POSTGRES_SSLMODE": "disable",
            }
        )
        self.assertEqual(local["DATABASES"]["default"]["HOST"], "127.0.0.1")

    def test_recovery_requires_separate_approval(self):
        env = {
            "NEXUS_EMAIL_HOST": "mail.example.invalid",
            "NEXUS_DEFAULT_FROM_EMAIL": "noreply@example.invalid",
        }
        self.assertEqual(smtp_settings(env, False, False)["EMAIL_TIMEOUT"], 10)
        with self.assertRaises(ImproperlyConfigured):
            smtp_settings(env, True, False)
        configured = smtp_settings(
            {**env, "NEXUS_PASSWORD_RESET_APPROVED": "true"}, True, False
        )
        self.assertTrue(configured["EMAIL_USE_TLS"])
        self.assertFalse(configured["EMAIL_USE_SSL"])

    def test_smtp_requires_secure_transport_valid_sender_and_paired_auth(self):
        env = {
            "NEXUS_PASSWORD_RESET_APPROVED": "true",
            "NEXUS_EMAIL_HOST": "mail.example.invalid",
            "NEXUS_DEFAULT_FROM_EMAIL": "noreply@example.invalid",
        }
        for key, value in (
            ("NEXUS_EMAIL_SECURITY", "none"),
            ("NEXUS_EMAIL_PORT", "0"),
            ("NEXUS_EMAIL_TIMEOUT", "0"),
            ("NEXUS_EMAIL_TIMEOUT", "61"),
            ("NEXUS_EMAIL_HOST_USER", "fixture"),
            ("NEXUS_EMAIL_HOST_PASSWORD", "fixture-only"),
            ("NEXUS_DEFAULT_FROM_EMAIL", "bad\r\nInjected: value"),
            ("NEXUS_EMAIL_HOST", "smtp://mail.example.invalid"),
        ):
            with self.subTest(key=key), self.assertRaises(
                ImproperlyConfigured
            ):
                smtp_settings({**env, key: value}, True, False)
        config = smtp_settings(
            {**env, "NEXUS_EMAIL_SECURITY": "ssl"}, True, False
        )
        self.assertEqual(config["EMAIL_PORT"], 465)
        self.assertTrue(config["EMAIL_USE_SSL"])
        self.assertFalse(config["EMAIL_USE_TLS"])

    def test_isolated_email_remains_local_capture(self):
        self.assertEqual(
            smtp_settings({}, False, True)["EMAIL_BACKEND"],
            "django.core.mail.backends.locmem.EmailBackend",
        )


class SecretAuditTests(unittest.TestCase):
    def test_real_literal_and_logging_are_flagged_but_values_are_not_reported(
        self,
    ):
        line = "POSTGRES_" + "PASSWORD: " + "fixture-sensitive-value"
        report = findings("docker-compose.yml", line)
        self.assertEqual(report[0]["kind"], "credential_literal")
        self.assertNotIn("fixture-sensitive-value", str(report))
        self.assertEqual(
            classify("workflow.yml", "echo $POSTGRES_" + "PASSWORD"),
            "secret_logging",
        )

    def test_variables_examples_and_explicit_test_canaries_are_distinct(self):
        key = "POSTGRES_" + "PASSWORD"
        self.assertIsNone(
            classify(".github/workflows/ci-cd.yml", '"' + key + '": password,')
        )
        self.assertIsNone(
            classify("compose.yml", key + ": ${LOCAL_PASSWORD:?required}")
        )
        self.assertIsNone(
            classify("tests/test_config.py", key + ": fixture-only-canary")
        )
        self.assertEqual(
            findings(".env.production", "")[0]["kind"], "sensitive_file"
        )

    def test_private_key_marker_is_detected_without_copying_material(self):
        line = "-----BEGIN " + "PRIVATE KEY-----"
        self.assertEqual(classify("credentials.pem", line), "private_key")

    def test_plaintext_starting_with_variable_prefix_is_not_exempt(self):
        key = "POSTGRES_" + "PASSWORD"
        for value in (
            "secret-production",
            "secrets.production",
            "os.production",
            "password",
        ):
            self.assertEqual(
                classify("compose.yml", key + ": " + value),
                "credential_literal",
            )
            self.assertEqual(
                classify("settings.py", key + " = '" + value + "'"),
                "credential_literal",
            )
