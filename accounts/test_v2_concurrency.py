"""PostgreSQL row locks ensure exactly one simultaneous refresh succeeds."""

from concurrent.futures import ThreadPoolExecutor
import threading

from django.core.cache import cache
from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)

from accounts.test_v2_auth import PASSWORD, User
from accounts.v2_services import (
    CookieRefreshToken,
    change_password,
    refresh_session,
)


class RefreshConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.assertEqual(connection.vendor, "postgresql")
        self.assertTrue(
            connection.settings_dict["NAME"].startswith("test_nexus_test_")
        )
        cache.clear()
        self.user = User.objects.create_user(
            email="refresh-race@example.invalid",
            username="refresh-race",
            password=PASSWORD,
        )

    def worker(self, raw, barrier):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '10s'")
                cursor.execute("SELECT pg_backend_pid()")
                backend = cursor.fetchone()[0]
            barrier.wait(timeout=10)
            try:
                _, token = refresh_session(raw)
                return backend, str(token)
            except AuthenticationFailed:
                return backend, None
        finally:
            connections.close_all()

    def test_simultaneous_refresh_only_one_rotation_commits(self):
        raw = str(CookieRefreshToken.for_user(self.user))
        barrier = threading.Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(self.worker, raw, barrier) for _ in range(2)
            ]
            results = [future.result(timeout=30) for future in futures]
        self.assertEqual(len({row[0] for row in results}), 2)
        successes = [token for _, token in results if token is not None]
        self.assertEqual(len(successes), 1)
        self.assertEqual(OutstandingToken.objects.count(), 2)
        self.assertEqual(BlacklistedToken.objects.count(), 1)
        with self.assertRaises(AuthenticationFailed):
            refresh_session(raw)
        # The winner's session remains usable.
        refresh_session(successes[0])

    def test_refresh_waiting_for_password_change_cannot_escape_revocation(
        self,
    ):
        from django.db import transaction

        raw = str(CookieRefreshToken.for_user(self.user))
        barrier = threading.Barrier(2)
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                User.objects.select_for_update().get(pk=self.user.pk)
                future = pool.submit(self.worker, raw, barrier)
                barrier.wait(timeout=10)
                change_password(self.user, PASSWORD, "Y8!sunrise-canyon-459")
            _, result = future.result(timeout=30)
        self.assertIsNone(result)
        self.assertEqual(OutstandingToken.objects.count(), 1)
        self.assertEqual(BlacklistedToken.objects.count(), 1)

    def legacy_worker(self, path, body, ready):
        from rest_framework.test import APIClient

        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '10s'")
                cursor.execute("SELECT pg_backend_pid()")
                ready.put(cursor.fetchone()[0])
            response = APIClient().post(path, body, format="json")
            return response.status_code, response.data
        finally:
            connections.close_all()

    def wait_for_database_lock(self, backend):
        import time

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_backend_pid() = ANY(pg_blocking_pids(%s))",
                    [backend],
                )
                row = cursor.fetchone()
            if row and row[0]:
                return
            threading.Event().wait(0.02)
        self.fail("The second connection never reached the user-row lock.")

    def test_legacy_refresh_waiting_for_logout_all_cannot_resurrect_session(
        self,
    ):
        from queue import Queue
        from django.db import transaction
        from rest_framework_simplejwt.tokens import RefreshToken
        from accounts.v2_services import logout_all

        old = RefreshToken.for_user(self.user)
        raw = str(old)
        OutstandingToken.objects.filter(jti=old["jti"]).delete()
        ready = Queue()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                User.objects.select_for_update().get(pk=self.user.pk)
                future = pool.submit(
                    self.legacy_worker,
                    "/api/token/refresh/",
                    {"refresh": raw},
                    ready,
                )
                self.wait_for_database_lock(ready.get(timeout=10))
                logout_all(self.user)
            code, data = future.result(timeout=30)
        self.assertEqual(code, 401)
        self.assertNotIn("access", data)
        self.assertNotIn("refresh", data)
        self.user.refresh_from_db()
        self.assertEqual(self.user.auth_version, 2)
        self.assertFalse(OutstandingToken.objects.exists())

    def test_legacy_login_waiting_for_password_change_rechecks_credentials(
        self,
    ):
        from queue import Queue
        from django.db import transaction

        ready = Queue()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                User.objects.select_for_update().get(pk=self.user.pk)
                future = pool.submit(
                    self.legacy_worker,
                    "/api/token/",
                    {"email": self.user.email, "password": PASSWORD},
                    ready,
                )
                self.wait_for_database_lock(ready.get(timeout=10))
                change_password(self.user, PASSWORD, "P4!cedar-valley-673")
            code, data = future.result(timeout=30)
        self.assertEqual(code, 401)
        self.assertNotIn("access", data)
        self.assertNotIn("refresh", data)
        self.assertFalse(OutstandingToken.objects.exists())

    def test_refresh_committed_before_revocation_is_also_revoked(self):
        from rest_framework.test import APIClient
        from accounts.v2_services import logout_all

        raw = str(CookieRefreshToken.for_user(self.user))
        _, replacement = refresh_session(raw)
        access = str(replacement.access_token)
        refresh = str(replacement)
        logout_all(self.user)
        with self.assertRaises(AuthenticationFailed):
            refresh_session(refresh)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION="Bearer " + access)
        self.assertEqual(client.get("/api/v2/auth/me/").status_code, 401)
