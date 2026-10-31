"""PostgreSQL locking across legacy voting and v2 lifecycle/share writers."""

from concurrent.futures import ThreadPoolExecutor
import queue
import threading
import time

from django.db import (
    close_old_connections,
    connection,
    connections,
    transaction,
)
from django.test import TransactionTestCase
from rest_framework.test import APIClient

from polls import management
from polls.models import Option, Poll, PollShareToken, Vote
from polls.views import cast_vote
from .test_v2_discovery import EFixtures


class PollEConcurrencyTests(EFixtures, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.assertEqual(connection.vendor, "postgresql")
        self.assertTrue(
            connection.settings_dict["NAME"].startswith("test_nexus_test_")
        )
        self.make_data()

    def worker(self, action, ready=None):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '10s'")
                cursor.execute("SET statement_timeout = '15s'")
                cursor.execute("SELECT pg_backend_pid()")
                pid = cursor.fetchone()[0]
            if ready is not None:
                ready.put(pid)
            return action()
        finally:
            connections.close_all()

    def wait_for_lock(self, pid):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_backend_pid() = ANY(pg_blocking_pids(%s))",
                    [pid],
                )
                if cursor.fetchone()[0]:
                    return
            time.sleep(0.02)
        self.fail("Worker did not reach the locked parent poll.")

    def request(self, client, method, path, body=None, **extra):
        return getattr(client, method)(
            path, body or {}, format="json", **extra
        ).status_code

    def test_first_vote_wins_against_waiting_configuration_and_option_changes(
        self,
    ):
        ready = queue.Queue()
        owner = self.auth()
        option = self.option(self.public)
        path = f"/api/polls/options/{option.pk}/"
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                Poll.objects.select_for_update().get(pk=self.public.pk)
                future = pool.submit(
                    self.worker,
                    lambda: self.request(owner, "delete", path),
                    ready,
                )
                self.wait_for_lock(ready.get(timeout=10))
                cast_vote(self.other, self.public.pk, option.pk)
            self.assertEqual(future.result(timeout=20), 400)
        self.assertEqual(Option.objects.filter(poll=self.public).count(), 2)
        self.public.refresh_from_db()
        self.assertIs(self.public.configuration_locked, True)

    def test_waiting_vote_observes_committed_configuration(self):
        ready = queue.Queue()
        voter = self.auth(self.other)
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                Poll.objects.select_for_update().get(pk=self.public.pk)
                future = pool.submit(
                    self.worker,
                    lambda: self.request(
                        voter, "post", self.vote_url(self.public)
                    ),
                    ready,
                )
                self.wait_for_lock(ready.get(timeout=10))
                management.update_poll(
                    self.owner, self.public.pk, {"question": "Updated first?"}
                )
            self.assertEqual(future.result(timeout=20), 200)
        self.public.refresh_from_db()
        self.assertEqual(self.public.question, "Updated first?")
        self.assertEqual(self.public.version, 3)

    def test_closing_wins_against_waiting_legacy_vote(self):
        ready = queue.Queue()
        voter = self.auth(self.other)
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                Poll.objects.select_for_update().get(pk=self.public.pk)
                future = pool.submit(
                    self.worker,
                    lambda: self.request(
                        voter, "post", self.vote_url(self.public)
                    ),
                    ready,
                )
                self.wait_for_lock(ready.get(timeout=10))
                management.transition(self.owner, self.public.pk, "close")
            self.assertEqual(future.result(timeout=20), 400)
        self.assertFalse(Vote.objects.exists())
        self.assertTrue(
            all(
                count == 0
                for count in self.public.options.values_list(
                    "votes_count", flat=True
                )
            )
        )

    def test_regeneration_invalidates_waiting_old_share_read(self):
        _, _, raw = management.change_share(
            self.owner, self.private.pk, "issue"
        )
        ready = queue.Queue()
        guest = APIClient()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                Poll.objects.select_for_update().get(pk=self.private.pk)
                future = pool.submit(
                    self.worker,
                    lambda: self.request(
                        guest,
                        "get",
                        self.detail(self.private),
                        HTTP_X_POLL_SHARE=raw,
                    ),
                    ready,
                )
                self.wait_for_lock(ready.get(timeout=10))
                management.change_share(
                    self.owner, self.private.pk, "regenerate"
                )
            self.assertEqual(future.result(timeout=20), 404)

    def test_simultaneous_share_issuance_has_one_winner(self):
        barrier = threading.Barrier(2)
        clients = [self.auth(), self.auth()]

        def issue(client):
            barrier.wait(timeout=10)
            return self.request(
                client, "post", self.action(self.private, "share")
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(self.worker, lambda c=c: issue(c)) for c in clients
            ]
            codes = sorted(future.result(timeout=20) for future in futures)
        self.assertEqual(codes, [201, 409])
        self.assertEqual(PollShareToken.objects.count(), 1)
        self.assertEqual(
            PollShareToken.objects.get(poll=self.private).generation, 1
        )

    def test_archiving_blocks_waiting_share_issuance(self):
        ready = queue.Queue()
        owner = self.auth()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                Poll.objects.select_for_update().get(pk=self.private.pk)
                future = pool.submit(
                    self.worker,
                    lambda: self.request(
                        owner, "post", self.action(self.private, "share")
                    ),
                    ready,
                )
                self.wait_for_lock(ready.get(timeout=10))
                management.transition(self.owner, self.private.pk, "archive")
            self.assertEqual(future.result(timeout=20), 400)
        self.assertFalse(PollShareToken.objects.exists())

    def test_reopening_restricts_waiting_legacy_results_read(self):
        Poll.objects.filter(pk=self.public.pk).update(
            results_visibility="after_closing", status="closed"
        )
        ready = queue.Queue()
        guest = APIClient()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                Poll.objects.select_for_update().get(pk=self.public.pk)
                future = pool.submit(
                    self.worker,
                    lambda: self.request(
                        guest, "get", self.legacy(self.public) + "results/"
                    ),
                    ready,
                )
                self.wait_for_lock(ready.get(timeout=10))
                management.transition(
                    self.owner, self.public.pk, "reopen", {"expires_at": None}
                )
            self.assertEqual(future.result(timeout=20), 403)
