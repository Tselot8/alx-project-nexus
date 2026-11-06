"""Local startup never falls back to production configuration."""

from pathlib import Path
import tempfile
from unittest import TestCase

from scripts.start_local import LocalSetupError, local_environment


class LocalStartupTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="nexus-startup-unit-")
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / ".env.local"
        self.values = {
            "DJANGO_SETTINGS_MODULE": "alx_project_nexus.settings_local",
            "NEXUS_LOCAL_SECRET_KEY": "non-secret-local-test-placeholder",
            "NEXUS_LOCAL_DB_HOST": "127.0.0.1",
            "NEXUS_LOCAL_DB_PORT": "55433",
            "NEXUS_LOCAL_DB_NAME": "nexus_local_fixture",
            "NEXUS_LOCAL_DB_USER": "nexus_local_fixture",
            "NEXUS_LOCAL_DB_PASSWORD": "non-secret-local-test-placeholder",
            "NEXUS_LOCAL_ALLOWED_HOSTS": "localhost,127.0.0.1",
        }

    def save(self):
        self.path.write_text(
            "\n".join(key + "=" + value for key, value in self.values.items()),
            encoding="utf-8",
        )

    def test_selects_local_before_django_and_discards_production_overrides(
        self,
    ):
        self.save()
        result = local_environment(
            self.path,
            {
                "DJANGO_SETTINGS_MODULE": "alx_project_nexus.settings",
                "DATABASE_URL": "not-a-connection",
                "POSTGRES_PASSWORD": "production-canary-not-a-secret",
                "NEXUS_TEST_DB_NAME": "nexus_test_fixture",
                "PATH": "kept",
            },
        )
        self.assertEqual(
            result["DJANGO_SETTINGS_MODULE"],
            "alx_project_nexus.settings_local",
        )
        for key in ("DATABASE_URL", "POSTGRES_PASSWORD", "NEXUS_TEST_DB_NAME"):
            self.assertNotIn(key, result)
        self.assertEqual(result["PATH"], "kept")

    def test_missing_local_file_never_reads_a_production_dotenv(self):
        self.path.with_name(".env").write_text(
            "POSTGRES_PASSWORD=production-canary-not-a-secret",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(LocalSetupError, "Git-ignored"):
            local_environment(self.path, {})

    def test_rejects_explicit_production_settings_selection(self):
        self.values["DJANGO_SETTINGS_MODULE"] = "alx_project_nexus.settings"
        self.save()
        with self.assertRaisesRegex(LocalSetupError, "settings_local"):
            local_environment(self.path, {})

    def test_reports_missing_names_without_echoing_values(self):
        self.values.pop("NEXUS_LOCAL_DB_PASSWORD")
        self.save()
        with self.assertRaises(LocalSetupError) as raised:
            local_environment(self.path, {})
        self.assertIn("NEXUS_LOCAL_DB_PASSWORD", str(raised.exception))
        self.assertNotIn(
            self.values["NEXUS_LOCAL_SECRET_KEY"], str(raised.exception)
        )

    def test_dotenv_values_are_literal_not_production_interpolation(self):
        self.values["NEXUS_LOCAL_DB_PASSWORD"] = "${POSTGRES_PASSWORD}"
        self.save()
        result = local_environment(
            self.path,
            {
                "POSTGRES_PASSWORD": "production-canary-not-a-secret",
            },
        )
        self.assertEqual(
            result["NEXUS_LOCAL_DB_PASSWORD"], "${POSTGRES_PASSWORD}"
        )

    def test_startup_never_enables_recovery(self):
        self.values["NEXUS_PASSWORD_RESET_ENABLED"] = "true"
        self.save()
        with self.assertRaisesRegex(LocalSetupError, "does not enable"):
            local_environment(self.path, {})
