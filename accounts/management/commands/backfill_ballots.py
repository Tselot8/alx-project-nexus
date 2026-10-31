"""Restricted, explicit operational import. Never invoked by migrations.

Rollout: drain ALL pre-F API/worker/admin writers; deploy F with writes paused;
dry-run bounded immutable source groups; enable the coordinated ballot writer;
apply batches with --confirm-frozen-writers; reconcile ALL polls; only then
set NEXUS_BALLOT_AUTHORITY=ballots. Runtime readiness checks remain mandatory.

A quarantined group is not repaired or partially imported. Output contains
reason counts, never user IDs, poll IDs, selections, tokens or database errors.
Retained voted_at is only the earliest *surviving* historical submission time.
Reversal after activation is not a rollback strategy: old writers would ignore
new ballots. Preserve both stores and roll forward.
"""

import json
from collections import Counter

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, transaction

from polls.ballots import backfill_group
from polls.ledger import HistoryUnavailable, snapshot
from polls.models import Poll, Vote


class Command(BaseCommand):
    help = "Import bounded historical groups or reconcile all poll ledgers."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--confirm-frozen-writers", action="store_true")
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--offset", type=int, default=0)
        parser.add_argument("--poll", type=str)
        parser.add_argument("--reconcile", action="store_true")

    def handle(self, *args, **options):
        try:
            return self.process(**options)
        except DatabaseError:
            raise CommandError(
                "Database operation failed; retry after restricted review."
            ) from None

    def process(self, **options):
        if not 1 <= options["limit"] <= 1000 or options["offset"] < 0:
            raise CommandError("Use limit 1..1000 and a nonnegative offset.")
        if options["apply"] and (
            options["dry_run"]
            or options["reconcile"]
            or not options["confirm_frozen_writers"]
            or settings.NEXUS_BALLOT_AUTHORITY != "bridge"
            or not settings.NEXUS_BALLOT_WRITES_ENABLED
        ):
            raise CommandError(
                "Apply requires bridge mode, enabled writes and "
                "--confirm-frozen-writers. "
                "Do not combine with dry-run/reconcile."
            )
        polls = Poll.objects.all()
        votes = Vote.objects.all()
        if options["poll"]:
            from uuid import UUID

            try:
                poll_id = UUID(options["poll"])
            except ValueError:
                raise CommandError("Invalid poll identifier.") from None
            polls = polls.filter(pk=poll_id)
            votes = votes.filter(poll_id=poll_id)
        counts = Counter()
        anomalies = Counter()
        if options["reconcile"]:
            if Vote.objects.exclude(
                poll_id__in=Poll.objects.values("id")
            ).exists():
                anomalies["missing_poll"] += 1
            for poll_id in (
                polls.order_by("id")
                .values_list("id", flat=True)
                .iterator(chunk_size=100)
            ):
                with transaction.atomic():
                    poll = Poll.objects.select_for_update().get(pk=poll_id)
                    try:
                        snapshot(poll, require_ready=True)
                    except HistoryUnavailable as error:
                        anomalies[error.reason] += 1
                    else:
                        counts["ready_polls"] += 1
            report = {
                "mode": "reconcile",
                "scope": "poll" if options["poll"] else "all",
                "ready": not anomalies,
                "counts": counts,
                "quarantined": anomalies,
            }
        else:
            offset, limit = options["offset"], options["limit"]
            # Stable across successful imports: never filter out converted
            # groups, because that would shift offsets and skip source votes.
            end = offset + limit + 1
            groups = list(
                votes.order_by("poll_id", "user_id")
                .values_list("poll_id", "user_id")
                .distinct()[offset:end]
            )
            for poll_id, user_id in groups[:limit]:
                try:
                    outcome = backfill_group(
                        poll_id, user_id, apply=options["apply"]
                    )
                except HistoryUnavailable as error:
                    anomalies[error.reason] += 1
                except Poll.DoesNotExist:
                    anomalies["missing_poll"] += 1
                else:
                    counts[outcome] += 1
            report = {
                "mode": "apply" if options["apply"] else "dry_run",
                "counts": counts,
                "quarantined": anomalies,
                "processed": min(len(groups), limit),
                "next_offset": offset + min(len(groups), limit),
                "more": len(groups) > limit,
            }
        self.stdout.write(json.dumps(report, sort_keys=True))
        if anomalies:
            raise CommandError(
                "Quarantined history remains; source records were preserved."
            )
