"""Atomic ballots, immutable historical evidence and gated authority."""

import io
import json
from datetime import timedelta
from unittest.mock import patch
import uuid

from django.contrib import admin
from django.contrib.auth.models import AnonymousUser
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import (
    RequestFactory,
    SimpleTestCase,
    TestCase,
    override_settings,
)
from django.utils import timezone
from rest_framework.exceptions import NotAuthenticated

from polls.ballots import backfill_group, submit
from polls.ledger import HistoryUnavailable, snapshot, validate_options
from polls.models import (
    AuditLog,
    Ballot,
    BallotSelection,
    Option,
    Vote,
)
from polls.views import cast_vote
from .test_v2_discovery import EFixtures


class BallotTests(EFixtures, TestCase):
    def ballot_url(self, poll=None):
        return self.action(poll or self.public, "ballots")

    def post(self, ids, *, user=None, poll=None):
        return self.auth(user or self.other).post(
            self.ballot_url(poll),
            {"option_ids": [str(i) for i in ids]},
            format="json",
        )

    def selected(self):
        return set(
            BallotSelection.objects.filter(
                ballot__user=self.other, poll=self.public
            ).values_list("option_id", flat=True)
        )

    def test_complete_replacement_and_idempotency_preserve_first_submission(
        self,
    ):
        first, second = list(self.public.options.all())
        initial = self.post([first.pk])
        self.assertEqual(initial.status_code, 200, initial.data)
        before = self.state()
        ballot = Ballot.objects.get(poll=self.public, user=self.other)
        submitted = ballot.submitted_at
        self.assertEqual(self.post([first.pk]).status_code, 200)
        self.assertEqual(before, self.state())
        self.assertEqual(self.post([second.pk]).status_code, 200)
        ballot.refresh_from_db()
        self.assertEqual(ballot.submitted_at, submitted)
        self.assertEqual(self.selected(), {second.pk})
        self.assertFalse(Vote.objects.exists())
        self.public.refresh_from_db()
        self.assertTrue(self.public.configuration_locked)
        self.assertEqual(self.public.version, 2)
        self.assertEqual(
            AuditLog.objects.filter(
                target_id=self.public.pk, action__icontains="vote"
            ).count(),
            2,
        )

    def test_multiple_choice_exact_minimum_maximum_and_full_replacement(self):
        third = Option.objects.create(poll=self.public, option_text="Water")
        self.public.allow_multiple = True
        self.public.min_selections = 2
        self.public.max_selections = 2
        self.public.save()
        first, second = list(self.public.options.exclude(pk=third.pk))
        for invalid in ([first.pk], [first.pk, second.pk, third.pk]):
            self.rejected(
                self.auth(self.other),
                "post",
                self.ballot_url(),
                400,
                {"option_ids": [str(i) for i in invalid]},
            )
        self.assertEqual(self.post([first.pk, second.pk]).status_code, 200)
        self.assertEqual(self.post([second.pk, third.pk]).status_code, 200)
        self.assertEqual(self.selected(), {second.pk, third.pk})
        self.rejected(
            self.auth(self.other), "post", self.vote_url(self.public), 400
        )

    def test_empty_duplicate_foreign_missing_and_invalid_input_leave_state(
        self,
    ):
        own = self.option(self.public).pk
        foreign = self.option(self.private).pk
        for values in (
            [],
            [own, own],
            [foreign],
            [uuid.uuid4()],
            [own, foreign],
        ):
            self.rejected(
                self.auth(self.other),
                "post",
                self.ballot_url(),
                400,
                {"option_ids": [str(i) for i in values]},
            )
        for field in (
            "user",
            "source",
            "submitted_at",
            "votes_count",
            "poll_id",
        ):
            self.rejected(
                self.auth(self.other),
                "post",
                self.ballot_url(),
                400,
                {"option_ids": [str(own)], field: str(self.owner.pk)},
            )
        self.rejected(
            self.auth(self.other),
            "post",
            self.ballot_url(),
            400,
            {"option_ids": ["not-a-uuid"]},
        )

    def test_invalid_replacement_and_failed_bulk_write_roll_back_everything(
        self,
    ):
        first, second = list(self.public.options.all())
        self.assertEqual(self.post([first.pk]).status_code, 200)
        self.rejected(
            self.auth(self.other),
            "post",
            self.ballot_url(),
            400,
            {"option_ids": []},
        )
        before = self.state()
        with patch(
            "polls.ballots.BallotSelection.objects.bulk_create",
            side_effect=RuntimeError("simulated failure"),
        ):
            with self.assertRaises(RuntimeError):
                submit(self.other, self.public.pk, [second.pk])
        self.assertEqual(before, self.state())

    def test_authentication_active_user_and_read_only_share(self):
        self.rejected(self.guest, "post", self.ballot_url(), 401)
        self.rejected(self.guest, "get", self.ballot_url(), 401)
        inactive_client = self.auth(self.other)
        self.other.is_active = False
        self.other.save(update_fields=["is_active"])
        with self.assertRaises(NotAuthenticated):
            submit(self.other, self.public.pk, [self.option(self.public).pk])
        with self.assertRaises(NotAuthenticated):
            submit(AnonymousUser(), self.public.pk, [])
        self.rejected(
            inactive_client,
            "post",
            self.ballot_url(),
            401,
            {"option_ids": [str(self.option(self.public).pk)]},
        )
        self.other.is_active = True
        self.other.save(update_fields=["is_active"])
        for user in (self.other, self.staff):
            self.rejected(
                self.auth(user),
                "post",
                self.ballot_url(self.private),
                404,
                {"option_ids": [str(self.option(self.private).pk)]},
            )
        token = (
            self.auth().post(self.action(self.private, "share")).data["token"]
        )
        self.rejected(
            self.auth(self.staff),
            "post",
            self.ballot_url(self.private),
            404,
            {"option_ids": [str(self.option(self.private).pk)]},
            HTTP_X_POLL_SHARE=token,
        )
        self.assertEqual(
            self.post(
                [self.option(self.private).pk],
                user=self.owner,
                poll=self.private,
            ).status_code,
            200,
        )

    def test_draft_closed_archived_and_exact_expiration_reject(self):
        for poll in (self.draft, self.closed, self.archived):
            self.rejected(
                self.auth(),
                "post",
                self.ballot_url(poll),
                400,
                {"option_ids": [str(uuid.uuid4())]},
            )
        now = timezone.now()
        self.public.expires_at = now
        self.public.save(update_fields=["expires_at"])
        with patch("polls.ballots.timezone.now", return_value=now):
            self.rejected(
                self.auth(self.other),
                "post",
                self.ballot_url(),
                400,
                {"option_ids": [str(self.option(self.public).pk)]},
            )

    def test_current_ballot_is_private_and_cannot_be_withdrawn(self):
        first = self.option(self.public)
        self.assertEqual(self.post([first.pk]).status_code, 200)
        own = self.auth(self.other).get(self.ballot_url())
        self.assertEqual(own.data["option_ids"], [str(first.pk)])
        self.assertTrue(own.data["submitted"])
        stranger = self.auth().get(self.ballot_url())
        self.assertEqual(stranger.data["option_ids"], [])
        self.assertFalse(stranger.data["submitted"])
        self.rejected(self.auth(self.other), "delete", self.ballot_url(), 405)
        self.assertIn("no-store", own["Cache-Control"])

    def test_legacy_and_v2_share_one_ledger_and_historical_votes_never_change(
        self,
    ):
        first, second = list(self.public.options.all())
        old = Vote.objects.create(
            user=self.other, poll=self.public, option=first
        )
        original = list(Vote.objects.values())
        self.assertEqual(self.post([second.pk]).status_code, 200)
        ballot = Ballot.objects.get(user=self.other, poll=self.public)
        self.assertEqual(ballot.source, "legacy")
        self.assertEqual(ballot.submitted_at, old.voted_at)
        receipt, count = cast_vote(self.other, self.public.pk, first.pk)
        self.assertEqual(receipt.option.pk, first.pk)
        self.assertEqual(count, 1)
        self.assertEqual(self.selected(), {first.pk})
        self.assertEqual(list(Vote.objects.values()), original)

    def test_legacy_multi_adds_idempotently_to_v2_complete_selection(self):
        self.public.allow_multiple = True
        self.public.save()
        first, second = list(self.public.options.all())
        self.assertEqual(self.post([first.pk]).status_code, 200)
        for _ in range(2):
            cast_vote(self.other, self.public.pk, second.pk)
        self.assertEqual(self.selected(), {first.pk, second.pk})
        self.assertEqual(Ballot.objects.count(), 1)
        self.assertFalse(Vote.objects.exists())
        self.assertEqual(self.post([second.pk]).status_code, 200)
        self.assertEqual(self.selected(), {second.pk})

    @override_settings(NEXUS_BALLOT_WRITES_ENABLED=False)
    def test_rollout_pause_rejects_both_write_routes(self):
        self.rejected(
            self.auth(self.other),
            "post",
            self.ballot_url(),
            503,
            {"option_ids": [str(self.option(self.public).pk)]},
        )
        self.rejected(
            self.auth(self.other), "post", self.vote_url(self.public), 503
        )

    def test_existing_native_incomplete_record_can_be_submitted(self):
        pending = Ballot.objects.create(user=self.other, poll=self.public)
        self.assertEqual(
            self.post([self.option(self.public).pk]).status_code, 200
        )
        pending.refresh_from_db()
        self.assertIsNotNone(pending.submitted_at)
        self.assertEqual(Ballot.objects.count(), 1)

    @override_settings(NEXUS_BALLOT_AUTHORITY="ballots")
    def test_reconciled_ballot_only_mode_accepts_native_writes(self):
        self.assertEqual(
            self.post([self.option(self.public).pk]).status_code, 200
        )
        self.assertEqual(snapshot(self.public).participants, 1)
        self.assertEqual(snapshot(self.public).unconverted, 0)
        self.assertFalse(Vote.objects.exists())

    def test_unknown_first_vote_lock_is_permanent_without_public_timestamp(
        self,
    ):
        self.public.configuration_locked = None
        self.public.save(update_fields=["configuration_locked"])
        updated_at = self.public.updated_at
        self.assertEqual(
            self.post([self.option(self.public).pk]).status_code, 200
        )
        self.public.refresh_from_db()
        self.assertIs(self.public.configuration_locked, True)
        self.assertEqual(self.public.updated_at, updated_at)


class HistoricalBackfillTests(EFixtures, TestCase):
    def history(self, user=None, poll=None, options=None):
        poll = poll or self.public
        return [
            Vote.objects.create(user=user or self.other, poll=poll, option=o)
            for o in (options or [self.option(poll)])
        ]

    def command(self, **kwargs):
        output = io.StringIO()
        call_command("backfill_ballots", stdout=output, **kwargs)
        return json.loads(output.getvalue())

    def test_dry_run_apply_idempotent_and_source_preservation(self):
        rows = self.history()
        before = list(Vote.objects.values())
        dry = self.command()
        self.assertEqual(dry["counts"], {"would_convert": 1})
        self.assertFalse(Ballot.objects.exists())
        applied = self.command(apply=True, confirm_frozen_writers=True)
        self.assertEqual(applied["counts"], {"converted": 1})
        self.assertEqual(
            self.command(apply=True, confirm_frozen_writers=True)["counts"],
            {"already_converted": 1},
        )
        ballot = Ballot.objects.get()
        self.assertEqual(ballot.source, "legacy")
        self.assertEqual(ballot.submitted_at, rows[0].voted_at)
        self.assertEqual(before, list(Vote.objects.values()))
        self.assertTrue(self.command(reconcile=True)["ready"])
        self.assertEqual(ballot.selections.count(), 1)

    def test_bounded_batches_have_stable_offsets_and_restart(self):
        self.history()
        self.history(user=self.owner)
        first = self.command(limit=1, apply=True, confirm_frozen_writers=True)
        self.assertTrue(first["more"])
        self.assertEqual(first["next_offset"], 1)
        self.assertEqual(Ballot.objects.count(), 1)
        self.command(
            offset=first["next_offset"],
            limit=1,
            apply=True,
            confirm_frozen_writers=True,
        )
        self.assertEqual(Ballot.objects.count(), 2)
        again = self.command(apply=True, confirm_frozen_writers=True)
        self.assertEqual(again["counts"], {"already_converted": 2})

    def test_apply_requires_explicit_freeze_and_bridge_mode(self):
        self.history()
        for settings in (
            {"NEXUS_BALLOT_WRITES_ENABLED": False},
            {"NEXUS_BALLOT_AUTHORITY": "ballots"},
        ):
            with override_settings(**settings), self.assertRaises(
                CommandError
            ):
                self.command(apply=True, confirm_frozen_writers=True)
        with self.assertRaises(CommandError):
            self.command(apply=True)
        self.assertFalse(Ballot.objects.exists())

    def test_invalid_single_choice_history_is_quarantined_and_never_repaired(
        self,
    ):
        self.history(options=list(self.public.options.all()))
        before = self.state()
        with self.assertRaises(CommandError):
            self.command(apply=True, confirm_frozen_writers=True)
        self.assertEqual(before, self.state())
        self.assertEqual(
            self.guest.get(self.action(self.public, "results")).status_code,
            503,
        )
        self.rejected(
            self.auth(self.other),
            "post",
            self.action(self.public, "ballots"),
            503,
            {"option_ids": [str(self.option(self.public).pk)]},
        )

    def test_cross_poll_history_is_quarantined_for_both_parents(self):
        Vote.objects.create(
            user=self.other, poll=self.public, option=self.option(self.private)
        )
        before = self.state()
        for poll in (self.public, self.private):
            with self.assertRaises(HistoryUnavailable):
                snapshot(poll)
        with self.assertRaises(CommandError):
            self.command(apply=True, confirm_frozen_writers=True)
        self.assertEqual(self.state(), before)

    def test_duplicate_and_missing_source_membership_validation(self):
        selected = [self.option(self.public).pk] * 2
        with self.assertRaises(HistoryUnavailable):
            validate_options(
                self.public, selected, set(selected), historical=True
            )
        with self.assertRaises(HistoryUnavailable):
            validate_options(
                self.public, [uuid.uuid4()], set(), historical=True
            )

    def test_provenance_conflict_and_partial_import_are_not_overwritten(self):
        self.history()
        pending = Ballot.objects.create(
            poll=self.public, user=self.other, source="legacy"
        )
        before = self.state()
        with self.assertRaises(HistoryUnavailable):
            backfill_group(self.public.pk, self.other.pk, apply=True)
        self.assertEqual(self.state(), before)
        self.assertIsNone(pending.submitted_at)

    def test_multi_history_preserves_earliest_retained_submission(self):
        self.public.allow_multiple = True
        self.public.save()
        rows = self.history(options=list(self.public.options.all()))
        earlier = timezone.now() - timedelta(days=2)
        Vote.objects.filter(pk=rows[0].pk).update(voted_at=earlier)
        before = list(Vote.objects.order_by("id").values())
        self.command(apply=True, confirm_frozen_writers=True)
        self.assertEqual(Ballot.objects.get().submitted_at, earlier)
        self.assertEqual(BallotSelection.objects.count(), 2)
        self.assertEqual(before, list(Vote.objects.order_by("id").values()))

    def test_bridge_cohorts_do_not_double_count_and_cutover_fails_closed(self):
        self.history()
        self.history(user=self.owner)
        self.assertEqual(snapshot(self.public).participants, 2)
        backfill_group(self.public.pk, self.other.pk, apply=True)
        self.assertEqual(snapshot(self.public).participants, 2)
        with override_settings(NEXUS_BALLOT_AUTHORITY="ballots"):
            self.assertEqual(
                self.guest.get(
                    self.action(self.public, "results")
                ).status_code,
                503,
            )
        with self.assertRaises(CommandError):
            self.command(reconcile=True)
        backfill_group(self.public.pk, self.owner.pk, apply=True)
        with override_settings(NEXUS_BALLOT_AUTHORITY="ballots"):
            result = self.guest.get(self.action(self.public, "results"))
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.data["authority"], "ballots")
            self.assertEqual(result.data["total_participants"], 2)
            self.assertEqual(result.data["total_selections"], 2)

    def test_backfill_output_contains_only_operational_counts(self):
        self.history()
        output = json.dumps(self.command())
        for sensitive in (
            str(self.other.pk),
            str(self.public.pk),
            self.other.email,
            str(self.option(self.public).pk),
            "option_text",
        ):
            self.assertNotIn(sensitive, output)

    def test_historical_votes_are_read_only_in_admin(self):
        request = RequestFactory().get("/admin/")
        request.user = self.staff
        model_admin = admin.site._registry[Vote]
        self.assertFalse(model_admin.has_add_permission(request))
        self.assertFalse(model_admin.has_change_permission(request))
        self.assertFalse(model_admin.has_delete_permission(request))

    def test_virtual_historical_ballot_get_is_read_only(self):
        old = self.history()[0]
        before = self.state()
        response = self.auth(self.other).get(
            self.action(self.public, "ballots")
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["submitted"])
        self.assertEqual(response.data["option_ids"], [str(old.option_id)])
        self.assertEqual(response.data["submitted_at"], old.voted_at)
        self.assertEqual(self.state(), before)

    def test_failed_import_rolls_back_ballot_selections_and_lock(self):
        self.history()
        before = self.state()
        with patch(
            "polls.ballots.BallotSelection.objects.bulk_create",
            side_effect=RuntimeError("simulated failure"),
        ):
            with self.assertRaises(RuntimeError):
                backfill_group(self.public.pk, self.other.pk, apply=True)
        self.assertEqual(self.state(), before)

    def test_native_and_unconverted_history_are_disjoint_bridge_cohorts(self):
        self.history()
        submit(self.owner, self.public.pk, [self.option(self.public).pk])
        self.assertEqual(snapshot(self.public).participants, 2)
        self.assertEqual(snapshot(self.public).unconverted, 1)
        backfill_group(self.public.pk, self.other.pk, apply=True)
        self.assertEqual(snapshot(self.public).participants, 2)
        self.assertEqual(snapshot(self.public).unconverted, 0)
        self.assertEqual(Vote.objects.count(), 1)

    def test_quarantine_output_does_not_expose_group_identity(self):
        self.history(options=list(self.public.options.all()))
        before = self.state()
        output = io.StringIO()
        with self.assertRaises(CommandError):
            call_command(
                "backfill_ballots",
                apply=True,
                confirm_frozen_writers=True,
                stdout=output,
            )
        report = json.loads(output.getvalue())
        self.assertEqual(
            report["quarantined"], {"single_choice_multiple_selections": 1}
        )
        for value in (
            str(self.other.pk),
            str(self.public.pk),
            str(self.option(self.public).pk),
            self.other.email,
        ):
            self.assertNotIn(value, output.getvalue())
        self.assertEqual(self.state(), before)

    def test_admin_parent_deletion_cannot_cascade_immutable_history(self):
        self.history()
        request = RequestFactory().get("/admin/")
        request.user = self.staff
        _, _, permissions, _ = admin.site._registry[
            type(self.public)
        ].get_deleted_objects([self.public], request)
        self.assertIn(Vote._meta.verbose_name, permissions)

    def test_invalid_native_participation_fails_reconciliation(self):
        Ballot.objects.create(
            user=self.other, poll=self.public, submitted_at=timezone.now()
        )
        before = self.state()
        with self.assertRaises(CommandError):
            self.command(reconcile=True)
        self.assertEqual(self.state(), before)

    def test_valid_sized_partial_import_is_quarantined_without_write_proof(
        self,
    ):
        self.public.allow_multiple = True
        self.public.save()
        rows = self.history(options=list(self.public.options.all()))
        ballot = Ballot.objects.create(
            poll=self.public,
            user=self.other,
            source="legacy",
            submitted_at=min(row.voted_at for row in rows),
        )
        BallotSelection.objects.create(
            ballot=ballot, poll=self.public, option=rows[0].option
        )
        before = self.state()
        with self.assertRaises(CommandError):
            self.command(apply=True, confirm_frozen_writers=True)
        with self.assertRaises(HistoryUnavailable):
            snapshot(self.public)
        self.assertEqual(before, self.state())

    def test_legacy_replacement_receipt_is_atomic_and_reconcilable(self):
        first, second = list(self.public.options.all())
        self.history(options=[first])
        backfill_group(self.public.pk, self.other.pk, apply=True)
        before = self.state()
        with patch(
            "polls.ballots.AuditLog.objects.create",
            side_effect=RuntimeError("simulated audit failure"),
        ):
            with self.assertRaises(RuntimeError):
                submit(self.other, self.public.pk, [second.pk])
        self.assertEqual(before, self.state())
        submit(self.other, self.public.pk, [second.pk])
        self.assertTrue(self.command(reconcile=True)["ready"])
        self.assertEqual(snapshot(self.public).counts[second.pk], 1)
        self.assertEqual(
            self.command(apply=True, confirm_frozen_writers=True)["counts"],
            {"already_converted": 1},
        )
        self.assertEqual(Vote.objects.get().option_id, first.pk)


class ResultsTests(EFixtures, TestCase):
    def url(self, poll=None):
        return self.action(poll or self.public, "results")

    def test_unique_participants_selections_and_percentage_denominators(self):
        self.public.allow_multiple = True
        self.public.save()
        first, second = list(self.public.options.all())
        submit(self.other, self.public.pk, [first.pk, second.pk])
        submit(self.owner, self.public.pk, [first.pk])
        result = self.guest.get(self.url())
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.data["total_participants"], 2)
        self.assertEqual(result.data["total_selections"], 3)
        options = {o["id"]: o for o in result.data["options"]}
        self.assertEqual(
            options[str(first.pk)]["percentage_of_participants"], 100
        )
        self.assertEqual(
            options[str(first.pk)]["percentage_of_selections"], 66.67
        )
        self.assertNotIn("user", json.dumps(result.data).lower())
        self.assertIn("no-store", result["Cache-Control"])

    def test_zero_votes_and_untrusted_counter_cache(self):
        self.public.options.update(votes_count=99)
        from django.core.cache import cache

        cache.set(f"poll_results:{self.public.pk}", {"total_votes": 500})
        result = self.guest.get(self.url())
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.data["total_participants"], 0)
        self.assertTrue(
            all(row["count"] == 0 for row in result.data["options"])
        )
        legacy = self.guest.get(self.legacy(self.public) + "results/")
        self.assertEqual(legacy.data["total_votes"], 0)
        detail = self.guest.get(self.legacy(self.public))
        self.assertTrue(
            all(o["votes_count"] == 0 for o in detail.data["options"])
        )
        self.assertEqual(
            list(self.public.options.values_list("votes_count", flat=True)),
            [99, 99],
        )

    def test_after_voting_remains_required_after_closing(self):
        self.public.results_visibility = "after_voting"
        self.public.save()
        self.assertEqual(self.guest.get(self.url()).status_code, 403)
        self.assertEqual(self.auth().get(self.url()).status_code, 200)
        submit(self.other, self.public.pk, [self.option(self.public).pk])
        self.assertEqual(
            self.auth(self.other).get(self.url()).status_code, 200
        )
        self.auth().post(self.action(self.public, "close"))
        self.assertEqual(self.guest.get(self.url()).status_code, 403)
        self.assertEqual(
            self.auth(self.other).get(self.url()).status_code, 200
        )

    def test_after_closing_relocks_on_reopen_and_expiration_unlocks(self):
        self.public.results_visibility = "after_closing"
        self.public.save()
        self.assertEqual(self.guest.get(self.url()).status_code, 403)
        self.auth().post(self.action(self.public, "close"))
        self.assertEqual(self.guest.get(self.url()).status_code, 200)
        self.assertEqual(
            self.auth()
            .post(
                self.action(self.public, "reopen"),
                {"expires_at": None},
                format="json",
            )
            .status_code,
            200,
        )
        self.assertEqual(self.guest.get(self.url()).status_code, 403)
        self.public.refresh_from_db()
        self.public.expires_at = timezone.now() - timedelta(seconds=1)
        self.public.save(update_fields=["expires_at"])
        self.assertEqual(self.guest.get(self.url()).status_code, 200)

    def test_private_share_grants_reads_not_participation(self):
        self.private.results_visibility = "after_voting"
        self.private.save()
        token = (
            self.auth().post(self.action(self.private, "share")).data["token"]
        )
        for user in (self.other, self.staff):
            self.assertEqual(
                self.auth(user)
                .get(self.url(self.private), HTTP_X_POLL_SHARE=token)
                .status_code,
                403,
            )
        self.assertEqual(
            self.guest.get(self.url(self.private)).status_code, 404
        )
        self.private.results_visibility = "immediate"
        self.private.save()
        self.assertEqual(
            self.guest.get(
                self.url(self.private), HTTP_X_POLL_SHARE=token
            ).status_code,
            200,
        )
        self.assertEqual(
            self.guest.get(
                self.url(self.public), HTTP_X_POLL_SHARE=token
            ).status_code,
            200,
        )
        another = type(self.private).objects.create(
            created_by=self.owner, question="Other private", is_public=False
        )
        self.assertEqual(
            self.guest.get(
                self.url(another), HTTP_X_POLL_SHARE=token
            ).status_code,
            404,
        )

    def test_restricted_counts_hidden_from_every_legacy_surface(self):
        self.public.results_visibility = "after_closing"
        self.public.save()
        for option in self.public.options.all():
            response = self.auth(self.other).post(
                self.vote_url(self.public, option)
            )
            self.assertEqual(response.status_code, 200)
            self.assertIsNone(response.data["votes_count"])
        legacy = self.guest.get(self.legacy(self.public))
        self.assertTrue(
            all(o["votes_count"] is None for o in legacy.data["options"])
        )
        self.assertEqual(
            self.guest.get(self.legacy(self.public) + "results/").status_code,
            403,
        )
        self.assertEqual(
            self.auth().get(self.legacy(self.public) + "results/").status_code,
            200,
        )


class RolloutConfigurationTests(SimpleTestCase):
    def test_production_defaults_pause_writes_and_keep_bridge_reads(self):
        import os
        from alx_project_nexus import settings as config

        with patch.dict(os.environ, {}, clear=True), patch.object(
            config, "_ISOLATED", False
        ):
            self.assertEqual(
                config._ballot_settings(),
                {
                    "NEXUS_BALLOT_AUTHORITY": "bridge",
                    "NEXUS_BALLOT_WRITES_ENABLED": False,
                },
            )

    def test_invalid_rollout_configuration_is_rejected(self):
        import os
        from django.core.exceptions import ImproperlyConfigured
        from alx_project_nexus import settings as config

        for key, value in (
            ("NEXUS_BALLOT_AUTHORITY", "automatic"),
            ("NEXUS_BALLOT_WRITES_ENABLED", "yes"),
        ):
            with patch.dict(os.environ, {key: value}, clear=True):
                with self.assertRaises(ImproperlyConfigured):
                    config._ballot_settings()
