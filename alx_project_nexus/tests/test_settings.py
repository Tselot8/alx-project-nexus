"""Database-independent isolation checks; no servers or containers are started.

Run without pytest's Django bootstrap:
    python -B -m unittest alx_project_nexus.tests.test_settings
"""

import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]

# Execute every settings probe in a fresh interpreter. Dotenv is observed,
# never read. Network and database connections are blocked before setup.
PROBE = r"""
import json
import os
import socket
import sys
from pathlib import Path

import dotenv
from django.core.exceptions import ImproperlyConfigured

dotenv_calls = []
def observe_dotenv(path, **kwargs):
    dotenv_calls.append(Path(path).name)
    return False

def forbidden_connection(*args, **kwargs):
    raise AssertionError("Configuration checks cannot connect to a service.")

dotenv.load_dotenv = observe_dotenv
socket.create_connection = forbidden_connection
socket.socket.connect = forbidden_connection
socket.socket.connect_ex = forbidden_connection

try:
    from django.conf import settings
    from django.db.backends.base.base import BaseDatabaseWrapper
    BaseDatabaseWrapper.connect = forbidden_connection
    database = settings.DATABASES["default"]
    result = {
        "debug": settings.DEBUG,
        "hosts": settings.ALLOWED_HOSTS,
        "cors_all": settings.CORS_ALLOW_ALL_ORIGINS,
        "cors": settings.CORS_ALLOWED_ORIGINS,
        "csrf": settings.CSRF_TRUSTED_ORIGINS,
        "ssl_redirect": settings.SECURE_SSL_REDIRECT,
        "secure_session": settings.SESSION_COOKIE_SECURE,
        "secure_csrf": settings.CSRF_COOKIE_SECURE,
        "engine": database["ENGINE"],
        "name": database["NAME"],
        "user": database["USER"],
        "host": database["HOST"],
        "port": database["PORT"],
        "secret_is_isolated": settings.SECRET_KEY == "isolated-test-key",
        "password_is_isolated": (
            database["PASSWORD"] == "isolated-test-password"
        ),
        "dotenv_calls": dotenv_calls,
    }
    if os.environ.get("A2_RUN_CHECKS") == "1":
        import django
        django.setup()
        from django.core.checks import ERROR, run_checks
        from django.core.cache import cache
        from django.core import mail
        result["check_errors"] = [
            item.id for item in run_checks() if item.level >= ERROR
        ]
        cache.set("a2-isolation-probe", "present", timeout=10)
        result["cache_works"] = cache.get("a2-isolation-probe") == "present"
        result["cache_location"] = settings.CACHES["default"]["LOCATION"]
        mail.send_mail("Probe", "Local capture only", "sender@example.invalid",
                       ["recipient@example.invalid"])
        result["captured_emails"] = len(mail.outbox)
    print(json.dumps(result))
except ImproperlyConfigured as error:
    print(json.dumps({
        "error_type": "ImproperlyConfigured", "error": str(error)
    }))
except Exception as error:
    print(json.dumps({"error_type": type(error).__name__,
                      "error": "Unexpected configuration failure."}))
"""


class SettingsIsolationTests(unittest.TestCase):
    def probe(self, profile, overrides=None, remove=(), checks=False):
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(
                ("DJANGO_", "POSTGRES_", "NEXUS_", "PYTEST_")
            )
            and key not in {"DATABASE_URL", "RENDER", "TESTING"}
        }
        env.update(
            {
                "DJANGO_SETTINGS_MODULE": (
                    "alx_project_nexus.settings" + profile
                ),
                "DJANGO_SECRET_KEY": "synthetic-production-key-" * 4,
                "DJANGO_ALLOWED_HOSTS": "api.example.invalid",
                "DJANGO_PROXY_MODE": "direct",
                "POSTGRES_HOST": "production.example.invalid",
                "POSTGRES_PORT": "6543",
                "POSTGRES_DB": "synthetic_production_database",
                "POSTGRES_USER": "synthetic_production_user",
                "POSTGRES_PASSWORD": "synthetic-production-password",
                "DATABASE_URL": "postgres://production.example.invalid/unused",
                "RENDER": "true",
                "TESTING": "True",
                "DJANGO_DEBUG": "True",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONPATH": str(ROOT),
            }
        )
        if profile in {"_local", "_test"}:
            prefix = "NEXUS_LOCAL" if profile == "_local" else "NEXUS_TEST"
            namespace = "nexus_local" if profile == "_local" else "nexus_test"
            env.update(
                {
                    f"{prefix}_SECRET_KEY": "isolated-test-key",
                    f"{prefix}_DB_HOST": "127.0.0.1",
                    f"{prefix}_DB_PORT": "55432",
                    f"{prefix}_DB_NAME": namespace + "_probe",
                    f"{prefix}_DB_USER": namespace + "_user",
                    f"{prefix}_DB_PASSWORD": "isolated-test-password",
                }
            )
        env["NEXUS_LOCAL_ALLOWED_HOSTS"] = "localhost,127.0.0.1,[::1]"
        env.update(overrides or {})
        for key in remove:
            env.pop(key, None)
        if checks:
            env["A2_RUN_CHECKS"] = "1"
        completed = subprocess.run(
            [sys.executable, "-B", "-"],
            input=PROBE,
            text=True,
            capture_output=True,
            cwd=ROOT,
            env=env,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    def assert_rejected(self, result, variable):
        self.assertEqual(result.get("error_type"), "ImproperlyConfigured")
        self.assertIn(variable, result["error"])
        self.assertNotIn("synthetic-production-password", result["error"])
        self.assertNotIn("isolated-test-password", result["error"])

    def test_isolated_profiles_ignore_production_credentials(self):
        for profile in ("_local", "_test"):
            with self.subTest(profile=profile):
                result = self.probe(profile)
                self.assertNotIn("error", result)
                self.assertEqual(
                    result["engine"], "django.db.backends.postgresql"
                )
                self.assertEqual(result["host"], "127.0.0.1")
                self.assertTrue(result["secret_is_isolated"])
                self.assertTrue(result["password_is_isolated"])
                self.assertNotIn("synthetic_production", result["name"])
                self.assertNotIn("synthetic_production", result["user"])
                expected = [".env.local"] if profile == "_local" else []
                self.assertEqual(result["dotenv_calls"], expected)

    def test_missing_isolated_credentials_fail_without_fallback(self):
        for profile, prefix in (
            ("_local", "NEXUS_LOCAL"),
            ("_test", "NEXUS_TEST"),
        ):
            for suffix in (
                "SECRET_KEY",
                "DB_HOST",
                "DB_NAME",
                "DB_USER",
                "DB_PASSWORD",
                "DB_PORT",
            ):
                key = f"{prefix}_{suffix}"
                with self.subTest(profile=profile, variable=key):
                    self.assert_rejected(
                        self.probe(profile, remove=(key,)), key
                    )

    def test_non_loopback_databases_are_rejected(self):
        for profile, prefix in (
            ("_local", "NEXUS_LOCAL"),
            ("_test", "NEXUS_TEST"),
        ):
            for host in ("production.example.invalid", "0.0.0.0", ""):
                key = f"{prefix}_DB_HOST"
                with self.subTest(profile=profile, host=host):
                    self.assert_rejected(self.probe(profile, {key: host}), key)

    def test_database_namespace_and_port_are_required(self):
        for profile, prefix in (
            ("_local", "NEXUS_LOCAL"),
            ("_test", "NEXUS_TEST"),
        ):
            for suffix, value in (
                ("DB_NAME", "postgres"),
                ("DB_USER", "postgres"),
                ("DB_PORT", "0"),
                ("DB_PORT", "65536"),
                ("DB_PORT", "invalid-sensitive-value"),
            ):
                key = f"{prefix}_{suffix}"
                with self.subTest(profile=profile, variable=key, value=value):
                    result = self.probe(profile, {key: value})
                    self.assert_rejected(result, key)
                    self.assertNotIn(
                        "invalid-sensitive-value", result["error"]
                    )

    def test_production_debug_cannot_be_enabled_by_render_or_testing(self):
        result = self.probe("")
        self.assertFalse(result["debug"])
        self.assertTrue(result["ssl_redirect"])
        self.assertTrue(result["secure_session"])
        self.assertTrue(result["secure_csrf"])
        self.assertEqual(result["dotenv_calls"], [".env"])

    def test_local_and_test_debug_are_explicit(self):
        self.assertTrue(self.probe("_local")["debug"])
        self.assertFalse(self.probe("_test")["debug"])

    def test_local_hosts_are_required_and_loopback_only(self):
        key = "NEXUS_LOCAL_ALLOWED_HOSTS"
        self.assert_rejected(self.probe("_local", remove=(key,)), key)
        for value in ("*", "localhost,production.example.invalid"):
            with self.subTest(value=value):
                self.assert_rejected(self.probe("_local", {key: value}), key)

    def test_local_origins_accept_only_loopback_origins(self):
        for key in (
            "NEXUS_LOCAL_CORS_ALLOWED_ORIGINS",
            "NEXUS_LOCAL_CSRF_TRUSTED_ORIGINS",
        ):
            for value in (
                "https://production.example.invalid",
                "http://*.example.invalid",
                "http://localhost:5173/path",
                "http://localhost:99999",
                "http://user:private@localhost:5173",
            ):
                with self.subTest(variable=key, origin=value):
                    result = self.probe("_local", {key: value})
                    self.assert_rejected(result, key)
                    self.assertNotIn("private", result["error"])
        result = self.probe(
            "_local",
            {
                "NEXUS_LOCAL_CORS_ALLOWED_ORIGINS": "http://localhost:5173",
                "NEXUS_LOCAL_CSRF_TRUSTED_ORIGINS": "http://localhost:5173",
            },
        )
        self.assertEqual(result["cors"], ["http://localhost:5173"])
        self.assertEqual(result["csrf"], ["http://localhost:5173"])

    def test_production_origins_are_explicit_https_only(self):
        for key in (
            "DJANGO_CORS_ALLOWED_ORIGINS",
            "DJANGO_CSRF_TRUSTED_ORIGINS",
        ):
            for value in (
                "*",
                "http://example.invalid",
                "https://*.example.invalid",
            ):
                with self.subTest(variable=key, origin=value):
                    self.assert_rejected(self.probe("", {key: value}), key)
        result = self.probe(
            "",
            {
                "DJANGO_ALLOWED_HOSTS": "api.example.invalid",
                "DJANGO_CORS_ALLOWED_ORIGINS": "https://app.example.invalid",
                "DJANGO_CSRF_TRUSTED_ORIGINS": "https://app.example.invalid",
            },
        )
        self.assertEqual(result["hosts"], ["api.example.invalid"])
        self.assertFalse(result["cors_all"])
        self.assertEqual(result["cors"], ["https://app.example.invalid"])
        self.assertEqual(result["csrf"], ["https://app.example.invalid"])

    def test_test_origins_cannot_inherit_production_allowlists(self):
        result = self.probe(
            "_test",
            {
                "DJANGO_ALLOWED_HOSTS": "*",
                "DJANGO_CORS_ALLOWED_ORIGINS": "*",
                "DJANGO_CSRF_TRUSTED_ORIGINS": "*",
            },
        )
        self.assertFalse(result["cors_all"])
        self.assertEqual(result["cors"], [])
        self.assertEqual(result["csrf"], [])
        self.assertIn("testserver", result["hosts"])

    def test_checks_cache_and_email_need_no_database_or_network(self):
        locations = []
        for profile in ("_local", "_test"):
            with self.subTest(profile=profile):
                result = self.probe(profile, checks=True)
                self.assertNotIn("error", result, result.get("error"))
                self.assertEqual(result["check_errors"], [])
                self.assertTrue(result["cache_works"])
                self.assertEqual(result["captured_emails"], 1)
                locations.append(result["cache_location"])
        self.assertNotEqual(*locations)


class ConfigurationFileTests(unittest.TestCase):
    def test_ci_is_test_only_and_has_no_secret_output_or_deployment(self):
        path = ROOT / ".github" / "workflows" / "ci-cd.yml"
        source = path.read_text(encoding="utf-8")
        workflow = yaml.load(source, Loader=yaml.BaseLoader)
        self.assertEqual(
            set(workflow["jobs"]),
            {"test", "frontend", "fullstack", "staging_artifact"},
        )
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        for forbidden in (
            "${{ secrets.",
            "manage.py migrate",
            "api.render.com",
            "printenv",
            "::add-mask::",
            "GITHUB_ENV",
        ):
            # GITHUB_ENV appears only in an explanatory comment.
            if forbidden == "GITHUB_ENV":
                self.assertNotIn('os.environ["GITHUB_ENV"]', source)
            else:
                self.assertNotIn(forbidden, source)
        scripts = [
            step.get("run", "") for step in workflow["jobs"]["test"]["steps"]
        ]
        test_step = next(script for script in scripts if "<<'PY'" in script)
        code = test_step.split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
        ast.parse(code)
        self.assertNotIn("print(", code)
        self.assertNotIn("echo ", code)
        self.assertIn("secrets.token_urlsafe", code)
        self.assertIn('"--publish", "127.0.0.1:5432:5432"', code)
        self.assertIn('"--env", "POSTGRES_PASSWORD"', code)

    def test_release_jobs_are_pinned_test_only_and_have_no_secret_inputs(self):
        workflow = yaml.load(
            (ROOT / ".github/workflows/ci-cd.yml").read_text(encoding="utf-8"),
            Loader=yaml.BaseLoader,
        )
        self.assertNotIn("pull_request_target", workflow["on"])
        self.assertEqual(
            workflow["jobs"]["fullstack"]["needs"], ["test", "frontend"]
        )
        for job in workflow["jobs"].values():
            for step in job["steps"]:
                if "uses" in step:
                    self.assertRegex(
                        step["uses"], r"^actions/[a-z-]+@[a-f0-9]{40}$"
                    )
                if step.get("uses", "").startswith("actions/checkout@"):
                    self.assertEqual(
                        step["with"]["persist-credentials"], "false"
                    )
        self.assertEqual(
            workflow["jobs"]["staging_artifact"]["needs"],
            ["test", "frontend"],
        )
        self.assertIn(
            "scripts/verify_staging.py",
            str(workflow["jobs"]["staging_artifact"]["steps"]),
        )
        frontend_steps = str(workflow["jobs"]["frontend"]["steps"])
        self.assertIn("npm ci", frontend_steps)
        self.assertIn("npm run check", frontend_steps)
        self.assertIn(
            "scripts/verify_fullstack.py",
            str(workflow["jobs"]["fullstack"]["steps"]),
        )

    def test_local_compose_has_separate_loopback_storage(self):
        source = (ROOT / "docker-compose.local.yml").read_text(
            encoding="utf-8"
        )
        compose = yaml.load(source, Loader=yaml.BaseLoader)
        self.assertEqual(set(compose["services"]), {"db-local"})
        service = compose["services"]["db-local"]
        self.assertTrue(service["ports"][0].startswith("127.0.0.1:"))
        self.assertIn("${NEXUS_LOCAL_DB_PASSWORD:?", source)
        self.assertEqual(
            compose["volumes"]["nexus-local-pgdata"]["name"],
            "project-nexus-local-pgdata",
        )

    def test_pytest_forces_test_profile_over_inherited_settings(self):
        source = (ROOT / "pytest.ini").read_text(encoding="utf-8")
        self.assertIn("--ds=alx_project_nexus.settings_test", source)
        self.assertIn("polls/tests", source)
        self.assertIn("python_files = test_*.py", source)


if __name__ == "__main__":
    unittest.main()
