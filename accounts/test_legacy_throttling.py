"""Legacy aliases must share the v2 connection-address abuse budgets."""

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from unittest.mock import patch
from rest_framework.test import APIClient

from accounts.v2_views import ConnectionAddressThrottle


class LegacyRateLimitTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.client = APIClient()

    def limited(self):
        return patch.dict(
            ConnectionAddressThrottle.THROTTLE_RATES,
            {
                "v2_login": "2/min",
                "v2_auth": "2/min",
            },
        )

    def test_legacy_login_is_limited_before_password_work(self):
        with self.limited():
            payload = {
                "email": "missing@example.invalid",
                "password": "Invalid!",
            }
            for _ in range(2):
                self.assertEqual(
                    self.client.post("/api/token/", payload).status_code, 401
                )
            blocked = self.client.post("/api/token/", payload)
            self.assertEqual(blocked.status_code, 429)
            self.assertIn("Retry-After", blocked)
            self.assertFalse(get_user_model().objects.exists())

    def test_legacy_and_v2_login_share_one_budget(self):
        with self.limited():
            payload = {
                "email": "missing@example.invalid",
                "password": "Invalid!",
            }
            self.assertEqual(
                self.client.post("/api/token/", payload).status_code, 401
            )
            self.assertEqual(
                self.client.post("/api/v2/auth/login/", payload).status_code,
                401,
            )
            self.assertEqual(
                self.client.post("/api/token/", payload).status_code, 429
            )
            self.assertEqual(
                self.client.post("/api/v2/auth/login/", payload).status_code,
                429,
            )

    def test_registration_aliases_and_refresh_share_the_auth_budget(self):
        with self.limited():
            for path in ("/api/accounts/register/", "/api/v2/auth/register/"):
                self.assertEqual(self.client.post(path, {}).status_code, 400)
            self.assertEqual(
                self.client.post("/api/accounts/register/", {}).status_code,
                429,
            )
            self.assertEqual(
                self.client.post("/api/token/refresh/", {}).status_code, 429
            )
            self.assertFalse(get_user_model().objects.exists())

    def test_forwarded_address_cannot_reset_the_legacy_budget(self):
        with self.limited():
            payload = {
                "email": "missing@example.invalid",
                "password": "Invalid!",
            }
            for address in ("192.0.2.1", "192.0.2.2"):
                self.client.post(
                    "/api/token/", payload, HTTP_X_FORWARDED_FOR=address
                )
            self.assertEqual(
                self.client.post(
                    "/api/token/", payload, HTTP_X_FORWARDED_FOR="192.0.2.3"
                ).status_code,
                429,
            )
            # A separate actual peer keeps a separate budget.
            self.assertEqual(
                self.client.post(
                    "/api/token/", payload, REMOTE_ADDR="127.0.0.2"
                ).status_code,
                401,
            )

    def test_legacy_successful_token_response_is_not_cacheable(self):
        user = get_user_model().objects.create_user(
            email="login@example.invalid",
            username="login",
            password="Fixture-only!Long-password-78",
        )
        response = self.client.post(
            "/api/token/",
            {
                "email": user.email,
                "password": "Fixture-only!Long-password-78",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data), {"access", "refresh"})
        self.assertIn("no-store", response.get("Cache-Control", ""))
