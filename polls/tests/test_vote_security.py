"""Voting eligibility and PostgreSQL locking regressions."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import queue
import threading
import time
from unittest.mock import patch
import uuid

from django.contrib.auth.models import AnonymousUser
from django.db import close_old_connections, connection, connections
from django.http import Http404
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.exceptions import NotAuthenticated
from rest_framework.test import APIClient

from polls.models import AuditLog, Option, Poll, Vote
from polls.views import cast_vote
from .test_poll_permissions import SecurityFixtures


class VoteSecurityTests(SecurityFixtures, TestCase):
    def url(self, poll, option=None):
        option = option or self.options[poll.pk][0]
        return reverse("cast-vote", args=[poll.pk, option.pk])

    def test_guest_and_inactive_voters_are_rejected(self):
        self.reject(self.client, "post", self.url(self.public), 401)
        self.reject(
            self.client_for(self.inactive), "post", self.url(self.public), 401
        )
        for user in (AnonymousUser(), self.inactive):
            before = self.snapshot()
            with self.assertRaises(NotAuthenticated):
                cast_vote(
                    user, self.public.pk, self.options[self.public.pk][0].pk
                )
            self.assertEqual(self.snapshot(), before)

    def test_private_vote_denial_applies_to_http_and_service(self):
        option = self.options[self.private.pk][0]
        for user in (self.other, self.staff):
            self.reject(
                self.client_for(user), "post", self.url(self.private), 404
            )
            before = self.snapshot()
            with self.assertRaises(Http404):
                cast_vote(user, self.private.pk, option.pk)
            self.assertEqual(self.snapshot(), before)
        response = self.client_for(self.owner).post(self.url(self.private))
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])

    def test_missing_and_cross_poll_targets_are_404_without_writes(self):
        client = self.client_for(self.other)
        for poll_id, option_id in (
            (self.public.pk, uuid.uuid4()),
            (uuid.uuid4(), self.options[self.public.pk][0].pk),
            (self.public.pk, self.options[self.private.pk][0].pk),
        ):
            url = reverse("cast-vote", args=[poll_id, option_id])
            self.reject(client, "post", url, 404)
            before = self.snapshot()
            with self.assertRaises(Http404):
                cast_vote(self.other, poll_id, option_id)
            self.assertEqual(self.snapshot(), before)

    def test_expired_and_exact_closing_time_reject_http_and_service(self):
        now = timezone.now()
        for closing_time in (now - timedelta(seconds=1), now):
            self.public.expires_at = closing_time
            self.public.save(update_fields=["expires_at"])
            before = self.snapshot()
            with patch("polls.views.timezone.now", return_value=now):
                self.reject(
                    self.client_for(self.other),
                    "post",
                    self.url(self.public),
                    400,
                )
                with self.assertRaises(ValueError):
                    cast_vote(
                        self.other,
                        self.public.pk,
                        self.options[self.public.pk][0].pk,
                    )
            self.assertEqual(self.snapshot(), before)

    def test_public_vote_replacement_and_body_identity_cannot_spoof_voter(
        self,
    ):
        client = self.client_for(self.other)
        first, second = self.options[self.public.pk]
        response = client.post(
            self.url(self.public, first),
            {
                "user": str(self.owner.pk),
                "user_id": str(self.owner.pk),
                "votes_count": 99,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(response.data),
            {
                "message",
                "poll_id",
                "option_id",
                "votes_count",
            },
        )
        self.reject(client, "delete", self.url(self.public, first), 405)
        vote = Vote.objects.get(poll=self.public)
        self.assertEqual(vote.user_id, self.other.pk)
        before = self.snapshot()
        self.assertEqual(
            client.post(self.url(self.public, first)).status_code, 200
        )
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(
            client.post(self.url(self.public, second)).status_code, 200
        )
        self.assertEqual(Vote.objects.filter(poll=self.public).count(), 1)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((first.votes_count, second.votes_count), (0, 1))

    def test_multiple_choice_per_option_behavior_remains_idempotent(self):
        self.public.allow_multiple = True
        self.public.save(update_fields=["allow_multiple"])
        first, second = self.options[self.public.pk]
        for option in (first, first, second):
            self.assertEqual(
                self.client_for(self.other)
                .post(self.url(self.public, option))
                .status_code,
                200,
            )
        self.assertEqual(
            Vote.objects.filter(user=self.other, poll=self.public).count(), 2
        )
        for option in (first, second):
            option.refresh_from_db()
            self.assertEqual(option.votes_count, 1)

    def test_unexpected_service_errors_are_not_reported_as_client_errors(self):
        before = self.snapshot()
        client = self.client_for(self.other)
        client.raise_request_exception = False
        with patch(
            "polls.views.cast_vote",
            side_effect=ValueError("Simulated internal failure"),
        ):
            response = client.post(self.url(self.public))
        self.assertEqual(response.status_code, 500)
        self.assertNotIn(b"Simulated internal failure", response.content)
        self.assertEqual(self.snapshot(), before)


class VoteConcurrencyTests(SecurityFixtures, TransactionTestCase):
    """Each worker uses its own connection to the disposable PostgreSQL DB."""

    def worker(self, action, ready=None):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '5s'")
                cursor.execute("SET statement_timeout = '10s'")
                cursor.execute("SELECT pg_backend_pid()")
                pid = cursor.fetchone()[0]
            if ready is not None:
                ready.put(pid)
            return action()
        finally:
            connections.close_all()

    def wait_for_database_lock(self, pid):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_stat_clear_snapshot()")
                cursor.execute(
                    "SELECT wait_event_type FROM pg_stat_activity "
                    "WHERE pid = %s",
                    [pid],
                )
                row = cursor.fetchone()
            if row and row[0] == "Lock":
                return
            time.sleep(0.02)
        self.fail("Worker did not wait on the parent PostgreSQL row lock.")

    def test_concurrent_single_choice_submissions_keep_one_vote(self):
        self.assertEqual(connection.vendor, "postgresql")
        barrier = threading.Barrier(2)

        def submit(option):
            barrier.wait(timeout=5)
            cast_vote(self.other, self.public.pk, option.pk)
            return True

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(self.worker, lambda opt=option: submit(opt))
                for option in self.options[self.public.pk]
            ]
            self.assertTrue(all(f.result(timeout=15) for f in futures))
        self.assertEqual(
            Vote.objects.filter(user=self.other, poll=self.public).count(), 1
        )
        for option in Option.objects.filter(poll=self.public):
            self.assertEqual(
                option.votes_count, Vote.objects.filter(option=option).count()
            )
        self.assertEqual(
            sum(
                Option.objects.filter(poll=self.public).values_list(
                    "votes_count", flat=True
                )
            ),
            1,
        )

    def test_waiting_vote_rechecks_private_visibility_after_lock(self):
        from django.db import transaction

        ready = queue.Queue()
        token_client = self.client_for(self.other)
        authorization = token_client._credentials["HTTP_AUTHORIZATION"]
        url = reverse(
            "cast-vote",
            args=[
                self.public.pk,
                self.options[self.public.pk][0].pk,
            ],
        )

        def submit():
            client = APIClient()
            client.credentials(HTTP_AUTHORIZATION=authorization)
            return client.post(url).status_code

        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                poll = Poll.objects.select_for_update().get(pk=self.public.pk)
                future = pool.submit(self.worker, submit, ready)
                self.wait_for_database_lock(ready.get(timeout=5))
                poll.is_public = False
                poll.save(update_fields=["is_public"])
            self.assertEqual(future.result(timeout=15), 404)
        self.assertFalse(Vote.objects.exists())
        self.assertFalse(AuditLog.objects.exists())
        option = self.options[self.public.pk][0]
        option.refresh_from_db()
        self.assertEqual(option.votes_count, 0)

    def test_waiting_option_update_rechecks_locked_parent_ownership(self):
        from django.db import transaction

        ready = queue.Queue()
        authorization = self.client_for(self.owner)._credentials[
            "HTTP_AUTHORIZATION"
        ]
        option = self.options[self.public.pk][0]
        url = reverse("option-update-delete", args=[option.pk])

        def submit():
            client = APIClient()
            client.credentials(HTTP_AUTHORIZATION=authorization)
            return client.patch(
                url,
                {"option_text": "Unauthorized after transfer"},
                format="json",
            ).status_code

        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                poll = Poll.objects.select_for_update().get(pk=self.public.pk)
                future = pool.submit(self.worker, submit, ready)
                self.wait_for_database_lock(ready.get(timeout=5))
                poll.created_by = self.other
                poll.save(update_fields=["created_by"])
            self.assertEqual(future.result(timeout=15), 403)
        option.refresh_from_db()
        self.assertEqual(option.option_text, "First")
        self.assertFalse(AuditLog.objects.exists())

    def test_waiting_poll_update_rechecks_locked_ownership(self):
        from django.db import transaction

        ready = queue.Queue()
        authorization = self.client_for(self.owner)._credentials[
            "HTTP_AUTHORIZATION"
        ]
        url = self.detail(self.public)

        def submit():
            client = APIClient()
            client.credentials(HTTP_AUTHORIZATION=authorization)
            return client.patch(
                url,
                {"question": "Unauthorized after transfer"},
                format="json",
            ).status_code

        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                poll = Poll.objects.select_for_update().get(pk=self.public.pk)
                future = pool.submit(self.worker, submit, ready)
                self.wait_for_database_lock(ready.get(timeout=5))
                poll.created_by = self.other
                poll.save(update_fields=["created_by"])
            self.assertEqual(future.result(timeout=15), 403)
        self.public.refresh_from_db()
        self.assertEqual(self.public.question, "Public question?")
        self.assertEqual(self.public.created_by_id, self.other.pk)
        self.assertFalse(AuditLog.objects.exists())

    def test_waiting_mode_change_checks_votes_committed_before_lock(self):
        from django.db import transaction

        ready = queue.Queue()
        authorization = self.client_for(self.owner)._credentials[
            "HTTP_AUTHORIZATION"
        ]
        url = self.detail(self.public)

        def submit():
            client = APIClient()
            client.credentials(HTTP_AUTHORIZATION=authorization)
            return client.patch(
                url, {"allow_multiple": True}, format="json"
            ).status_code

        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                Poll.objects.select_for_update().get(pk=self.public.pk)
                future = pool.submit(self.worker, submit, ready)
                self.wait_for_database_lock(ready.get(timeout=5))
                cast_vote(
                    self.other,
                    self.public.pk,
                    self.options[self.public.pk][0].pk,
                )
            self.assertEqual(future.result(timeout=15), 400)
        self.public.refresh_from_db()
        self.assertFalse(self.public.allow_multiple)
        self.assertEqual(Vote.objects.count(), 1)
        self.assertEqual(AuditLog.objects.count(), 1)
