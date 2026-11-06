"""Local startup never falls back to production configuration."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from scripts import start_local

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


class ReadinessTests(TestCase):
    api = "http://127.0.0.1:8000"
    frontend = "http://localhost:5173"

    def response(self, body=None, content_type="application/json", status=200):
        if body is None:
            body = json.dumps({"csrf_token": "a" * 64}).encode()
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.status = status
        response.headers = {"Content-Type": content_type}
        response.read.return_value = body
        return response

    def vite_response(self):
        return self.response(
            b"export function createHotContext() {}", "text/javascript"
        )

    def processes(self):
        return [Mock(**{"poll.return_value": None}) for _ in range(2)]

    def wait(self, responses, processes=None):
        opener = Mock()
        opener.open.side_effect = responses
        with redirect_stdout(io.StringIO()) as output:
            start_local.wait_for_servers(
                processes or self.processes(),
                self.api,
                self.frontend,
                timeout=0,
                opener=opener,
            )
        return opener, output.getvalue()

    def test_http_readiness_does_not_require_any_process_banners(self):
        opener, output = self.wait(
            [self.response(), self.vite_response(), self.response()]
        )
        self.assertEqual(
            [call.args[0] for call in opener.open.call_args_list],
            [
                self.api + "/api/v2/auth/csrf/",
                self.frontend + "/@vite/client",
                self.frontend + "/api/v2/auth/csrf/",
            ],
        )
        for component in (
            "Django API",
            "Vite frontend",
            "Vite-to-Django proxy",
        ):
            self.assertIn(component + " HTTP ready.", output)

    def test_unavailable_django_is_identified_before_vite_or_proxy(self):
        with self.assertRaisesRegex(LocalSetupError, "Django API.*connection"):
            self.wait([URLError("secret driver details must not be reported")])

    def test_vite_http_failure_is_distinguished_from_django(self):
        with self.assertRaisesRegex(
            LocalSetupError, "Vite frontend.*HTTP 503"
        ):
            self.wait([self.response(), self.response(status=503)])

    def test_proxy_html_fallback_is_not_treated_as_backend_readiness(self):
        with self.assertRaisesRegex(
            LocalSetupError, "Vite-to-Django proxy.*HTML"
        ):
            self.wait(
                [
                    self.response(),
                    self.vite_response(),
                    self.response(b"<html>Vite fallback</html>", "text/html"),
                ]
            )

    def test_invalid_csrf_payloads_are_rejected_without_printing_body(self):
        payloads = (
            b"not-json-sensitive-value",
            b"[]",
            b'{"csrf_token":"wrong"}',
            b'{"csrf_token":32}',
            b'{"csrf_token":"' + b"a" * 64 + b'","extra":1}',
            b"x" * 262145,
        )
        for body in payloads:
            with self.subTest(length=len(body)):
                opener = Mock()
                opener.open.return_value = self.response(body)
                ready, reason = start_local.probe_http(
                    opener, self.api, "csrf"
                )
                self.assertFalse(ready)
                self.assertNotIn("sensitive-value", reason)
                self.assertNotIn("wrong", reason)

    def test_vite_requires_javascript_client_not_arbitrary_http_200(self):
        for body, mime in ((b"OK", "text/plain"), (b"<html/>", "text/html")):
            with self.subTest(mime=mime):
                opener = Mock()
                opener.open.return_value = self.response(body, mime)
                self.assertFalse(
                    start_local.probe_http(opener, self.frontend, "vite")[0]
                )

    def test_http_error_is_closed_and_only_its_status_is_reported(self):
        body = io.BytesIO(b"sensitive error body")
        error = HTTPError(self.api, 302, "secret redirect", {}, body)
        opener = Mock()
        opener.open.side_effect = error
        self.assertEqual(
            start_local.probe_http(opener, self.api, "csrf"),
            (False, "HTTP 302"),
        )
        self.assertTrue(body.closed)

    def test_explicit_redirect_header_is_rejected(self):
        response = self.response()
        response.headers["Location"] = "https://untrusted.example.invalid/"
        opener = Mock()
        opener.open.return_value = response
        self.assertEqual(
            start_local.probe_http(opener, self.api, "csrf"),
            (False, "unexpected redirect"),
        )

    def test_http_readiness_retries_transient_connection_failures(self):
        opener = Mock()
        opener.open.side_effect = [
            URLError("not listening yet"),
            self.response(),
            self.vite_response(),
            self.response(),
        ]
        with (
            patch.object(start_local.time, "sleep"),
            redirect_stdout(io.StringIO()),
        ):
            start_local.wait_for_servers(
                self.processes(),
                self.api,
                self.frontend,
                timeout=2,
                opener=opener,
            )
        self.assertEqual(opener.open.call_count, 4)

    def test_exited_child_cannot_be_hidden_by_a_successful_http_response(self):
        processes = self.processes()
        processes[0].poll.side_effect = [None, 7]
        with self.assertRaisesRegex(LocalSetupError, "Django API exited.*7"):
            self.wait([self.response()], processes)

    def test_logs_strip_ansi_credentials_urls_and_unlabelled_tokens(self):
        env = {
            "NEXUS_LOCAL_DB_PASSWORD": "fixture password/private",
            "NEXUS_LOCAL_SECRET_KEY": "fixture password/private-longer",
        }
        raw = (
            "\x1b[32mVite ready\x1b[0m\n"
            "EADDRINUSE: address already in use\n"
            "fixture password/private-longer\n"
            "fixture%20password%2Fprivate\n"
            "Authorization: Bearer fixture-access\n"
            "X-Poll-Share: fixture-share\n"
            "https://user:pass@example.invalid/reset/private-value\n"
            + "q" * 43
            + "\n"
        )
        result = start_local.sanitized_log(io.BytesIO(raw.encode()), env)
        self.assertIn("Vite ready", result)
        self.assertIn("EADDRINUSE", result)
        for secret in (
            "\x1b",
            "fixture",
            "private",
            "example.invalid",
            "q" * 43,
            "-longer",
        ):
            self.assertNotIn(secret, result)

    def test_log_tail_discards_truncated_lines_and_bounds_output(self):
        raw = b"X" * 70000 + b"\n" + b"Ready\n" * 30
        result = start_local.sanitized_log(io.BytesIO(raw), {})
        self.assertNotIn("X", result)
        self.assertEqual(len(result.splitlines()), 20)
        self.assertEqual(
            start_local.sanitized_log(io.BytesIO(), {}), "(no output captured)"
        )

    def test_main_failure_preserves_cleanup_and_sanitizes_child_output(self):
        processes = self.processes()
        for process in processes:
            process.wait.side_effect = lambda timeout, p=process: setattr(
                p.poll, "return_value", 0
            )
        pending = iter(processes)
        env = {"NEXUS_LOCAL_DB_PASSWORD": "local-fixture-secret"}

        def launch(*args, **kwargs):
            kwargs["stdout"].write(b"Bind failed: local-fixture-secret\n")
            return next(pending)

        with (
            patch.object(
                start_local.sys, "argv", ["start_local.py", "--smoke"]
            ),
            patch.object(start_local, "local_environment", return_value=env),
            patch.object(start_local, "verify_database") as database,
            patch.object(start_local, "require_free") as free,
            patch.object(start_local.shutil, "which", return_value="node"),
            patch.object(Path, "is_file", return_value=True),
            patch.object(
                start_local.subprocess, "run", return_value=Mock(returncode=0)
            ),
            patch.object(start_local.subprocess, "Popen", side_effect=launch),
            patch.object(
                start_local,
                "wait_for_servers",
                side_effect=LocalSetupError(
                    "Vite frontend failed HTTP readiness."
                ),
            ),
            redirect_stdout(io.StringIO()),
        ):
            with self.assertRaises(LocalSetupError) as raised:
                start_local.main()
        message = str(raised.exception)
        self.assertIn("Vite frontend", message)
        self.assertIn("Django output (sanitized)", message)
        self.assertIn("Vite output (sanitized)", message)
        self.assertIn("Bind failed", message)
        self.assertNotIn("local-fixture-secret", message)
        database.assert_called_once_with(env)
        self.assertEqual(
            [call.args[0] for call in free.call_args_list], [8000, 5173]
        )
        for process in processes:
            process.terminate.assert_called_once_with()
            process.wait.assert_called_once_with(timeout=10)
