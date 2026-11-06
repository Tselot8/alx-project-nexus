"""Read-only PostgreSQL release evidence and production TLS boundaries."""

import io
import json
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.http import HttpResponse
from django.middleware.security import SecurityMiddleware
from django.test import (
    RequestFactory,
    SimpleTestCase,
    TransactionTestCase,
    override_settings,
)
from django.test.utils import CaptureQueriesContext

from accounts.management.commands.release_preflight import database_report
from polls.ledger import snapshot
from polls.models import Ballot, Vote
from .test_v2_discovery import EFixtures


class ReleasePreflightTests(EFixtures, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.make_data()

    def run_report(self, **options):
        output = io.StringIO()
        call_command(
            "release_preflight", database=True, stdout=output, **options
        )
        return json.loads(output.getvalue())

    def test_preflight_uses_read_only_repeatable_snapshot_and_changes_nothing(
        self,
    ):
        before = self.state()

        def inspect(*args, **kwargs):
            with connection.cursor() as cursor:
                cursor.execute("SHOW transaction_read_only")
                self.assertEqual(cursor.fetchone()[0], "on")
                cursor.execute("SHOW transaction_isolation")
                self.assertEqual(cursor.fetchone()[0], "repeatable read")
            return snapshot(*args, **kwargs)

        with patch(
            "accounts.management.commands.release_preflight.snapshot",
            side_effect=inspect,
        ), CaptureQueriesContext(connection) as queries:
            report = self.run_report(require_cutover_ready=True)
        self.assertFalse(report["deployment_authorized"])
        self.assertTrue(report["database"]["schema_ready"])
        self.assertTrue(report["database"]["cutover_ready"])
        self.assertEqual(before, self.state())
        self.assertFalse(any("FOR UPDATE" in row["sql"] for row in queries))
        self.assertFalse(
            any(
                row["sql"]
                .lstrip()
                .upper()
                .startswith(("INSERT", "UPDATE", "DELETE", "ALTER", "CREATE"))
                for row in queries
            )
        )

    def test_cutover_requires_preserving_and_converting_all_history(
        self,
    ):
        vote = Vote.objects.create(
            user=self.other, poll=self.public, option=self.option(self.public)
        )
        source = list(Vote.objects.values())
        before = self.state()
        report = self.run_report()
        self.assertEqual(report["database"]["unconverted_groups"], 1)
        self.assertFalse(report["database"]["cutover_ready"])
        with self.assertRaises(CommandError):
            self.run_report(require_cutover_ready=True)
        self.assertEqual(before, self.state())
        for _ in range(2):
            call_command(
                "backfill_ballots",
                apply=True,
                confirm_frozen_writers=True,
                stdout=io.StringIO(),
            )
        self.assertTrue(
            self.run_report(require_cutover_ready=True)["database"][
                "cutover_ready"
            ]
        )
        self.assertEqual(source, list(Vote.objects.values()))
        self.assertEqual(Ballot.objects.count(), 1)
        self.assertTrue(Vote.objects.filter(pk=vote.pk).exists())

    def test_anomalies_report_counts_not_identifiers_and_never_repair_source(
        self,
    ):
        for option in self.public.options.all():
            Vote.objects.create(
                user=self.other, poll=self.public, option=option
            )
        before = self.state()
        output = io.StringIO()
        with self.assertRaises(CommandError):
            call_command("release_preflight", database=True, stdout=output)
        report = json.loads(output.getvalue())
        self.assertEqual(
            report["database"]["quarantined"],
            {"single_choice_multiple_selections": 1},
        )
        for identity in (
            str(self.public.pk),
            str(self.other.pk),
            self.other.email,
        ):
            self.assertNotIn(identity, output.getvalue())
        self.assertEqual(before, self.state())

    def test_pending_migrations_stop_before_ledger_reads(self):
        with patch(
            "django.db.migrations.executor.MigrationExecutor.migration_plan",
            return_value=[object()],
        ):
            self.assertEqual(
                database_report(),
                {"schema_ready": False, "pending_migrations": 1},
            )

    def test_nested_transaction_is_refused_without_database_changes(self):
        with transaction.atomic(), self.assertRaisesRegex(
            CommandError, "own read-only"
        ):
            self.run_report()

    def test_security_warnings_cannot_be_broadly_waived(self):
        with self.assertNumQueries(0), self.assertRaisesRegex(
            CommandError, "Only HSTS"
        ):
            call_command(
                "release_preflight",
                production=True,
                acknowledge_warning=["security.W004"],
                stdout=io.StringIO(),
            )

    def test_production_gate_cannot_pass_under_test_settings(self):
        with self.assertNumQueries(0), self.assertRaises(CommandError):
            call_command(
                "release_preflight", production=True, stdout=io.StringIO()
            )


class ProductionTlsTests(SimpleTestCase):
    def request(self):
        return RequestFactory().get(
            "/api/v2/auth/csrf/",
            HTTP_HOST="api.example.invalid",
            HTTP_X_FORWARDED_PROTO="https",
        )

    @override_settings(
        SECURE_SSL_REDIRECT=True,
        ALLOWED_HOSTS=["api.example.invalid"],
        SECURE_PROXY_SSL_HEADER=None,
    )
    def test_direct_tls_mode_ignores_spoofed_forwarded_protocol(self):
        middleware = SecurityMiddleware(lambda request: HttpResponse("ready"))
        self.assertEqual(middleware(self.request()).status_code, 301)

    @override_settings(
        SECURE_SSL_REDIRECT=True,
        ALLOWED_HOSTS=["api.example.invalid"],
        SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
    )
    def test_explicit_trusted_proxy_avoids_https_redirect_loop(self):
        middleware = SecurityMiddleware(lambda request: HttpResponse("ready"))
        self.assertEqual(middleware(self.request()).status_code, 200)
