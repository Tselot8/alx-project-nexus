"""Separate PostgreSQL connections exercise the shared parent-lock order."""

from concurrent.futures import ThreadPoolExecutor
import queue
import threading

from django.db import connection, transaction
from django.test import TransactionTestCase

from polls.ballots import backfill_group, submit
from polls.ledger import snapshot
from polls.models import Ballot, BallotSelection, Poll, Vote
from polls.views import cast_vote
from . import test_vote_security as old_concurrency
from .test_v2_discovery import EFixtures


class BallotConcurrencyTests(EFixtures, TransactionTestCase):
    worker = old_concurrency.VoteConcurrencyTests.worker
    wait_for_database_lock = (
        old_concurrency.VoteConcurrencyTests.wait_for_database_lock
    )

    def setUp(self):
        self.make_data()
        super().setUp()

    def simultaneous(self, *actions):
        self.assertEqual(connection.vendor, "postgresql")
        barrier = threading.Barrier(len(actions))

        def execute(action):
            barrier.wait(timeout=5)
            action()
            return True

        with ThreadPoolExecutor(max_workers=len(actions)) as pool:
            futures = [
                pool.submit(self.worker, lambda a=a: execute(a))
                for a in actions
            ]
            self.assertTrue(all(f.result(timeout=20) for f in futures))

    def assert_consistent(self, selections):
        self.assertEqual(Ballot.objects.filter(poll=self.public).count(), 1)
        self.assertEqual(
            BallotSelection.objects.filter(poll=self.public).count(),
            selections,
        )
        ledger = snapshot(self.public)
        for option in self.public.options.all():
            self.assertEqual(option.votes_count, ledger.counts[option.pk])

    def test_concurrent_first_submissions_create_one_complete_ballot(self):
        first, second = list(self.public.options.all())
        self.simultaneous(
            lambda: submit(self.other, self.public.pk, [first.pk]),
            lambda: submit(self.other, self.public.pk, [second.pk]),
        )
        self.assert_consistent(1)
        self.assertFalse(Vote.objects.exists())
        self.public.refresh_from_db()
        self.assertEqual(self.public.version, 2)

    def test_concurrent_complete_replacements_never_merge_partial_sets(self):
        self.public.allow_multiple = True
        self.public.save()
        first, second = list(self.public.options.all())
        submit(self.other, self.public.pk, [first.pk, second.pk])
        submitted = Ballot.objects.get().submitted_at
        self.simultaneous(
            lambda: submit(self.other, self.public.pk, [first.pk]),
            lambda: submit(self.other, self.public.pk, [second.pk]),
        )
        self.assert_consistent(1)
        self.assertEqual(Ballot.objects.get().submitted_at, submitted)

    def test_legacy_and_v2_concurrent_first_writes_share_one_ledger(self):
        first, second = list(self.public.options.all())
        self.simultaneous(
            lambda: submit(self.other, self.public.pk, [first.pk]),
            lambda: cast_vote(self.other, self.public.pk, second.pk),
        )
        self.assert_consistent(1)
        self.assertFalse(Vote.objects.exists())

    def test_concurrent_legacy_multi_additions_preserve_both_options(self):
        self.public.allow_multiple = True
        self.public.save()
        first, second = list(self.public.options.all())
        self.simultaneous(
            lambda: cast_vote(self.other, self.public.pk, first.pk),
            lambda: cast_vote(self.other, self.public.pk, second.pk),
        )
        self.assert_consistent(2)

    def test_backfill_and_vote_do_not_overwrite_current_selections(self):
        first, second = list(self.public.options.all())
        source = Vote.objects.create(
            user=self.other, poll=self.public, option=first
        )
        original = list(Vote.objects.values())
        self.simultaneous(
            lambda: backfill_group(self.public.pk, self.other.pk, apply=True),
            lambda: submit(self.other, self.public.pk, [second.pk]),
        )
        self.assert_consistent(1)
        self.assertEqual(Ballot.objects.get().source, "legacy")
        self.assertEqual(Ballot.objects.get().submitted_at, source.voted_at)
        self.assertEqual(BallotSelection.objects.get().option_id, second.pk)
        self.assertEqual(list(Vote.objects.values()), original)

    def test_concurrent_backfill_is_idempotent(self):
        Vote.objects.create(
            user=self.other, poll=self.public, option=self.option(self.public)
        )
        self.simultaneous(
            lambda: backfill_group(self.public.pk, self.other.pk, apply=True),
            lambda: backfill_group(self.public.pk, self.other.pk, apply=True),
        )
        self.assertEqual(Ballot.objects.count(), 1)
        self.assertEqual(BallotSelection.objects.count(), 1)
        self.assertEqual(Vote.objects.count(), 1)

    def test_waiting_ballot_rechecks_closed_state_before_writing(self):
        ready = queue.Queue()
        option = self.option(self.public)

        def attempt():
            from polls.services import PollExpiredError

            try:
                submit(self.other, self.public.pk, [option.pk])
            except PollExpiredError:
                return "closed"
            return "accepted"

        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                poll = Poll.objects.select_for_update().get(pk=self.public.pk)
                future = pool.submit(self.worker, attempt, ready)
                self.wait_for_database_lock(ready.get(timeout=5))
                poll.status = "closed"
                poll.save(update_fields=["status"])
            self.assertEqual(future.result(timeout=15), "closed")
        self.assertFalse(Ballot.objects.exists())
        self.assertFalse(Vote.objects.exists())

    def test_results_wait_for_atomic_replacement(self):
        first, second = list(self.public.options.all())
        submit(self.other, self.public.pk, [first.pk])
        ready = queue.Queue()

        def read():
            with transaction.atomic():
                poll = Poll.objects.select_for_update().get(pk=self.public.pk)
                return dict(snapshot(poll).counts)

        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                Poll.objects.select_for_update().get(pk=self.public.pk)
                future = pool.submit(self.worker, read, ready)
                self.wait_for_database_lock(ready.get(timeout=5))
                submit(self.other, self.public.pk, [second.pk])
            self.assertEqual(future.result(timeout=15), {second.pk: 1})

    def test_legacy_clock_is_evaluated_after_waiting_for_poll_lock(self):
        from datetime import timedelta
        from unittest.mock import patch
        from django.utils import timezone
        from polls.services import PollExpiredError

        now = timezone.now()
        self.public.expires_at = now + timedelta(minutes=10)
        self.public.save(update_fields=["expires_at"])
        ready = queue.Queue()

        def attempt():
            try:
                cast_vote(
                    self.other, self.public.pk, self.option(self.public).pk
                )
            except PollExpiredError:
                return "expired"
            return "accepted"

        with patch("polls.views.timezone.now", return_value=now) as clock:
            with ThreadPoolExecutor(max_workers=1) as pool:
                with transaction.atomic():
                    Poll.objects.select_for_update().get(pk=self.public.pk)
                    future = pool.submit(self.worker, attempt, ready)
                    self.wait_for_database_lock(ready.get(timeout=5))
                    clock.assert_not_called()
                    clock.return_value = now + timedelta(hours=1)
                self.assertEqual(future.result(timeout=15), "expired")
        self.assertFalse(Ballot.objects.exists())
        self.assertFalse(Vote.objects.exists())

    def test_option_lock_wait_cannot_accept_a_ballot_after_expiration(self):
        from datetime import timedelta
        from unittest.mock import patch
        from django.utils import timezone
        from polls.models import Option
        from polls.services import PollExpiredError

        now = timezone.now()
        self.public.expires_at = now + timedelta(minutes=10)
        self.public.save(update_fields=["expires_at"])
        option = self.option(self.public)
        ready = queue.Queue()

        def attempt():
            try:
                submit(self.other, self.public.pk, [option.pk])
            except PollExpiredError:
                return "expired"
            return "accepted"

        with patch("polls.ballots.timezone.now", return_value=now) as clock:
            with ThreadPoolExecutor(max_workers=1) as pool:
                with transaction.atomic():
                    # Emulate an external option writer holding only this row.
                    Option.objects.select_for_update().get(pk=option.pk)
                    future = pool.submit(self.worker, attempt, ready)
                    self.wait_for_database_lock(ready.get(timeout=5))
                    self.assertTrue(clock.called)
                    clock.return_value = now + timedelta(hours=1)
                self.assertEqual(future.result(timeout=15), "expired")
        self.assertFalse(Ballot.objects.exists())
        self.assertFalse(Vote.objects.exists())
