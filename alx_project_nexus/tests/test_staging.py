"""Staging preparation never grants deployment or database-write authority."""

import logging
from pathlib import Path
import tempfile
from unittest.mock import patch

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError, connection
from django.test import (
    Client,
    SimpleTestCase,
    TestCase,
    TransactionTestCase,
    override_settings,
)
from django.test.utils import CaptureQueriesContext

from alx_project_nexus.deployment import (
    SafeServerLogFilter,
    frontend_settings,
    validate_artifact,
)
from accounts.management.commands.release_preflight import database_report


class StagingArtifactTests(SimpleTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="nexus-l-artifact-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / "assets").mkdir()
        (self.root / "assets/app-a1b2c3.js").write_text(
            "document.title = 'Project Nexus';",
            encoding="utf-8",
        )
        (self.root / "index.html").write_text(
            '<html><div id="root"></div>'
            '<script src="/assets/app-a1b2c3.js"></script></html>',
            encoding="utf-8",
        )
        static = self.root / "collected"
        static.mkdir()
        (static / "admin.css").write_text("body{}", encoding="utf-8")
        middleware = list(settings.MIDDLEWARE)
        middleware.insert(1, "alx_project_nexus.deployment.ArtifactMiddleware")
        self.override = self.settings(
            NEXUS_SERVE_FRONTEND=True,
            NEXUS_FRONTEND_DIST=self.root,
            STATIC_ROOT=static,
            MIDDLEWARE=middleware,
            WHITENOISE_AUTOREFRESH=False,
            WHITENOISE_USE_FINDERS=False,
            WHITENOISE_ALLOW_ALL_ORIGINS=False,
        )
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.client = Client()

    def body(self, response):
        try:
            return b"".join(response.streaming_content)
        finally:
            response.close()

    def test_root_and_deep_links_serve_same_uncached_shell(self):
        for path in (
            "/",
            "/polls",
            "/polls/id/manage",
            "/profile",
            "/missing",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn(b'id="root"', self.body(response))
                self.assertEqual(
                    response["Cache-Control"], "private, no-store"
                )
                self.assertEqual(response["Referrer-Policy"], "no-referrer")
                self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(self.client.post("/polls").status_code, 405)

    def test_assets_static_and_head_work_with_debug_false(self):
        self.assertFalse(settings.DEBUG)
        for path, expected in (
            ("/assets/app-a1b2c3.js", b"Project Nexus"),
            ("/static/admin.css", b"body{}"),
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn(expected, self.body(response))
                self.assertNotIn("Access-Control-Allow-Origin", response)
                head = self.client.head(path)
                self.assertEqual(head.status_code, 200)
                self.assertEqual(self.body(head), b"")
                self.assertIn("Cache-Control", response)

    def test_reserved_and_sensitive_paths_never_become_html_success(self):
        for path in (
            "/api/missing/",
            "/api/v2/missing/",
            "/health/missing/",
            "/static/missing.js",
            "/assets/missing.js",
            "/.env",
            "/.env.local",
            "/src/main.tsx",
            "/swagger/missing/",
            "/assets/../../.env",
            "/assets/app-a1b2c3.js.map",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 404)
                self.assertNotContains(
                    response,
                    'id="root"',
                    status_code=404,
                )

    def test_bad_host_is_rejected_before_static_or_health_responses(self):
        for path in ("/assets/app-a1b2c3.js", "/health/live/", "/polls"):
            with self.subTest(path=path):
                self.assertEqual(
                    Client()
                    .get(path, HTTP_HOST="untrusted.invalid")
                    .status_code,
                    400,
                )

    def test_opt_in_preserves_legacy_landing_when_disabled(self):
        with self.settings(NEXUS_SERVE_FRONTEND=False):
            self.assertRedirects(
                Client().get("/"),
                "/swagger/",
                fetch_redirect_response=False,
            )
            self.assertEqual(Client().get("/profile").status_code, 404)

    def test_configuration_rejects_missing_or_unexpected_assets(self):
        with self.assertRaises(ImproperlyConfigured):
            frontend_settings(
                {"NEXUS_SERVE_FRONTEND": "yes"},
                self.root,
                False,
            )
        with self.assertRaises(ImproperlyConfigured):
            validate_artifact(self.root / "absent")
        (self.root / "assets/debug.map").write_text("{}", encoding="utf-8")
        with self.assertRaises(ImproperlyConfigured):
            validate_artifact(self.root)

    def test_stale_or_cross_origin_build_references_fail_closed(self):
        for source in (
            "/assets/missing.js",
            "/src/main.tsx",
            "https://external.invalid/code.js",
            "/assets/../index.html",
        ):
            with self.subTest(source=source):
                (self.root / "index.html").write_text(
                    '<script src="' + source + '"></script>',
                    encoding="utf-8",
                )
                with self.assertRaises(ImproperlyConfigured):
                    validate_artifact(self.root)

    def test_local_and_test_cannot_enable_artifact_serving_from_environment(
        self,
    ):
        result = frontend_settings(
            {"NEXUS_SERVE_FRONTEND": "true"},
            self.root,
            True,
        )
        self.assertFalse(result["NEXUS_SERVE_FRONTEND"])

    def test_health_is_generic_uncached_and_live_never_connects(self):
        # SimpleTestCase itself rejects all database access.
        response = self.client.get("/health/live/")
        self.assertEqual(response.json(), {"status": "ok"})
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(self.client.post("/health/live/").status_code, 405)
        with patch(
            "alx_project_nexus.deployment.transaction.atomic",
            side_effect=DatabaseError("sensitive internal connection details"),
        ):
            response = self.client.get("/health/ready/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "unavailable"})
        self.assertNotContains(response, "sensitive", status_code=503)

    def test_safe_log_filter_drops_all_request_and_exception_material(self):
        record = logging.LogRecord(
            "django.request",
            logging.ERROR,
            "ignored",
            1,
            "password=%s /?share=secret",
            ("sensitive-value",),
            (ValueError, ValueError("sensitive details"), None),
        )
        record.status_code = 500
        record.exc_text = "sensitive traceback"
        record.stack_info = "sensitive stack"
        self.assertTrue(SafeServerLogFilter().filter(record))
        self.assertEqual(record.getMessage(), "HTTP response status=500")
        self.assertIsNone(record.exc_info)
        self.assertIsNone(record.exc_text)
        self.assertIsNone(record.stack_info)

    def test_https_and_proxy_security_remain_before_asset_serving(self):
        with self.settings(
            SECURE_SSL_REDIRECT=True,
            SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
        ):
            self.assertEqual(
                Client().get("/assets/app-a1b2c3.js").status_code,
                301,
            )
            response = Client().get(
                "/assets/app-a1b2c3.js",
                HTTP_X_FORWARDED_PROTO="https",
            )
            self.assertEqual(response.status_code, 200)
            self.body(response)


class StagingDatabaseReadinessTests(TransactionTestCase):
    def test_ready_uses_read_only_transaction_without_changing_data(self):
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get("/health/ready/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        sql = [row["sql"].upper() for row in queries]
        self.assertTrue(any("SET TRANSACTION READ ONLY" in row for row in sql))
        self.assertTrue(any("STATEMENT_TIMEOUT" in row for row in sql))
        self.assertFalse(
            any(
                row.lstrip().startswith(
                    ("INSERT", "UPDATE", "DELETE", "ALTER")
                )
                for row in sql
            )
        )

    def test_readiness_fails_closed_for_pending_migrations(self):
        with patch(
            "alx_project_nexus.deployment.MigrationExecutor"
        ) as executor:
            executor.return_value.migration_plan.return_value = [object()]
            response = self.client.get("/health/ready/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "unavailable"})

    def test_fresh_database_does_not_imply_voting_or_deploy_authorization(
        self,
    ):
        report = database_report()
        self.assertTrue(report["schema_ready"])
        self.assertTrue(report["cutover_ready"])
        # This reads only; no importer, flags or data mutation is involved.
        self.assertEqual(
            report["counts"],
            {
                "polls": 0,
                "legacy_rows": 0,
                "ballots": 0,
            },
        )


@override_settings(
    SECURE_SSL_REDIRECT=True,
    CSRF_COOKIE_SECURE=True,
    SESSION_COOKIE_SECURE=True,
    NEXUS_REFRESH_COOKIE_SECURE=True,
)
class StagingSecureSessionTests(TestCase):
    def test_https_cookie_session_rotation_csrf_and_logout_with_real_jwts(
        self,
    ):
        import json

        client = Client(enforce_csrf_checks=True)
        token = client.get("/api/v2/auth/csrf/", secure=True).json()[
            "csrf_token"
        ]

        def post(path, data, csrf, origin="https://testserver"):
            return client.post(
                "/api/v2/auth/" + path,
                data=json.dumps(data),
                content_type="application/json",
                secure=True,
                HTTP_X_CSRFTOKEN=csrf,
                HTTP_ORIGIN=origin,
            )

        response = post(
            "register/",
            {
                "email": "staging-session@example.invalid",
                "username": "staging-session",
                "password": "Staging!fixture-maple-78426",
            },
            token,
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertNotIn("refresh", data)
        access, csrf = data["access"], data["csrf_token"]
        cookie = response.cookies["nexus_v2_refresh_token"]
        self.assertTrue(cookie["secure"])
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")
        self.assertEqual(cookie["path"], "/api/v2/auth/")
        first_refresh = cookie.value
        csrf_cookie = client.cookies["csrftoken"].value
        self.assertEqual(
            client.get(
                "/api/v2/auth/me/",
                secure=True,
                HTTP_AUTHORIZATION="Bearer " + access,
            ).status_code,
            200,
        )
        rejected = post("refresh/", {}, csrf, "https://untrusted.invalid")
        self.assertEqual(rejected.status_code, 403)
        refreshed = post("refresh/", {}, csrf)
        self.assertEqual(refreshed.status_code, 200)
        self.assertNotEqual(
            refreshed.cookies["nexus_v2_refresh_token"].value,
            first_refresh,
        )
        self.assertNotIn("refresh", refreshed.json())
        # The existing refresh contract preserves CSRF rather than returning
        # a replacement token. Assert that contract and keep the original.
        self.assertEqual(set(refreshed.json()), {"access", "expires_in"})
        self.assertEqual(client.cookies["csrftoken"].value, csrf_cookie)
        self.assertEqual(post("logout/", {}, csrf).status_code, 204)
        self.assertEqual(post("refresh/", {}, csrf).status_code, 401)
