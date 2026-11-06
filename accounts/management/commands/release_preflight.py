"""Read-only release evidence; never authorizes deployment or cutover."""

from collections import Counter
import json

from django.conf import settings
from django.core.checks import WARNING, run_checks
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connection, transaction
from django.db.migrations.executor import MigrationExecutor

from polls.ledger import HistoryUnavailable, snapshot
from polls.models import Ballot, Option, Poll, Vote


CONSTRAINTS = {
    "ck_poll_status",
    "ck_poll_results_vis",
    "ck_poll_min_sel",
    "ck_poll_max_sel",
    "ck_poll_single_limits",
    "ck_poll_version",
    "fk_selection_ballot_poll",
    "fk_selection_option_poll",
    "uq_option_id_poll",
    "uq_ballot_poll_user",
    "uq_ballot_id_poll",
    "uq_selection_ballot_option",
    "ck_user_auth_version",
}


def database_report():
    report = {"mode": "read_only_snapshot", "quarantined": Counter()}
    with transaction.atomic():
        with connection.cursor() as cursor:
            # First statement: read-only snapshot, without row locks.
            cursor.execute(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
            )
            cursor.execute("SET LOCAL statement_timeout = '30s'")
            cursor.execute("SET LOCAL lock_timeout = '5s'")
            executor = MigrationExecutor(connection)
            pending = executor.migration_plan(
                executor.loader.graph.leaf_nodes()
            )
            if pending:
                return {
                    "schema_ready": False,
                    "pending_migrations": len(pending),
                }
            cursor.execute(
                "SELECT conname, convalidated FROM pg_constraint "
                "WHERE connamespace = current_schema()::regnamespace "
                "AND conname = ANY(%s)",
                [sorted(CONSTRAINTS)],
            )
            constraints = dict(cursor.fetchall())
        report["schema_ready"] = all(
            constraints.get(name) for name in CONSTRAINTS
        )
        if not report["schema_ready"]:
            report["missing_or_unvalidated_constraints"] = sum(
                not constraints.get(name) for name in CONSTRAINTS
            )
            return report
        report["counts"] = {
            "polls": Poll.objects.count(),
            "legacy_rows": Vote.objects.count(),
            "ballots": Ballot.objects.count(),
        }
        report["unconverted_groups"] = 0
        report["counter_drift_options"] = 0
        report["ready_polls"] = 0
        if Vote.objects.exclude(
            poll_id__in=Poll.objects.values("id")
        ).exists():
            report["quarantined"]["missing_poll"] += 1
        # Repeatable-read provides a coherent snapshot without FOR UPDATE.
        for poll in Poll.objects.order_by("pk").iterator(chunk_size=100):
            try:
                ledger = snapshot(poll, require_ready=False)
            except HistoryUnavailable as error:
                report["quarantined"][error.reason] += 1
                continue
            report["unconverted_groups"] += ledger.unconverted
            if not ledger.unconverted:
                report["ready_polls"] += 1
            report["counter_drift_options"] += sum(
                count != ledger.counts[option_id]
                for option_id, count in Option.objects.filter(
                    poll=poll
                ).values_list("pk", "votes_count")
            )
        report["cutover_ready"] = (
            not report["quarantined"] and not report["unconverted_groups"]
        )
    return report


class Command(BaseCommand):
    help = "Configuration and optional read-only PostgreSQL release evidence."

    def add_arguments(self, parser):
        parser.add_argument("--production", action="store_true")
        parser.add_argument(
            "--acknowledge-warning",
            action="append",
            default=[],
            choices=["security.W005", "security.W021"],
            help="Explicitly review HSTS subdomain/preload policy only.",
        )
        parser.add_argument("--database", action="store_true")
        parser.add_argument("--require-cutover-ready", action="store_true")

    def handle(self, *args, **options):
        if not (options["production"] or options["database"]):
            raise CommandError(
                "Select --production and/or --database explicitly."
            )
        if options["require_cutover_ready"] and not options["database"]:
            raise CommandError("--require-cutover-ready requires --database.")
        if not set(options["acknowledge_warning"]) <= {
            "security.W005",
            "security.W021",
        }:
            raise CommandError(
                "Only HSTS subdomain/preload warnings can be acknowledged."
            )
        report = {"deployment_authorized": False}
        blocked = False
        if options["production"]:
            if settings.SETTINGS_MODULE != "alx_project_nexus.settings":
                raise CommandError(
                    "Production checks require the production settings module."
                )
            issues = run_checks(include_deployment_checks=True, databases=[])
            acknowledged = set(options["acknowledge_warning"])
            report["acknowledged_warnings"] = sorted(acknowledged)
            report["configuration_issues"] = sorted(
                item.id
                for item in issues
                if item.level >= WARNING and item.id not in acknowledged
            )
            blocked = bool(report["configuration_issues"])
        if options["database"]:
            if connection.in_atomic_block:
                raise CommandError(
                    "Database preflight requires its own "
                    "read-only transaction."
                )
            try:
                report["database"] = database_report()
            except DatabaseError:
                raise CommandError(
                    "Read-only database preflight failed; inspect privately."
                ) from None
            data = report["database"]
            blocked = (
                blocked
                or not data["schema_ready"]
                or bool(data.get("quarantined"))
            )
            if options["require_cutover_ready"]:
                blocked = blocked or not data.get("cutover_ready", False)
        self.stdout.write(json.dumps(report, sort_keys=True))
        if blocked:
            raise CommandError("Release gates failed; no state was changed.")
