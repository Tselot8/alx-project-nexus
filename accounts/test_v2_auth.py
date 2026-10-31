"""Real-token v2 account security and legacy compatibility regression tests."""

import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from accounts.models import UserProfile
from accounts.v2_services import CookieRefreshToken

User = get_user_model()
PASSWORD = "R7!violet-cloud-862"
NEW_PASSWORD = "W9!copper-harbor-493"
COOKIE = "nexus_v2_refresh_token"


def url(name):
    return reverse("auth_v2:" + name)


class AccountFixtures:
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            email="v2@example.invalid", username="v2user", password=PASSWORD
        )
        cls.other = User.objects.create_user(
            email="other-v2@example.invalid",
            username="other-v2",
            password=PASSWORD,
        )
        cls.inactive = User.objects.create_user(
            email="inactive@example.invalid",
            username="inactive",
            password=PASSWORD,
            is_active=False,
        )

    def setUp(self):
        self.assertEqual(connection.vendor, "postgresql")
        cache.clear()

    def csrf_client(self):
        client = APIClient(enforce_csrf_checks=True)
        response = client.get(url("csrf"))
        self.assertEqual(response.status_code, 200)
        client.defaults["HTTP_X_CSRFTOKEN"] = response.data["csrf_token"]
        return client

    def signed_in(self, user=None):
        user = user or self.user
        client = self.csrf_client()
        response = client.post(
            url("login"),
            {
                "email": user.email,
                "password": PASSWORD,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        client.defaults["HTTP_X_CSRFTOKEN"] = response.data["csrf_token"]
        client.credentials(
            HTTP_AUTHORIZATION="Bearer " + response.data["access"]
        )
        return client, response

    def assert_no_refresh_json(self, response, raw):
        self.assertNotIn(raw, json.dumps(response.data))
        self.assertNotIn("refresh", response.data)
        self.assertEqual(response["Cache-Control"], "private, no-store")


class AuthenticationTests(AccountFixtures, TestCase):
    def test_registration_validates_password_and_returns_safe_account(self):
        client = self.csrf_client()
        for password in ("12345678", "password", "short", "newperson123"):
            with self.subTest(password_kind=len(password)):
                response = client.post(
                    url("register"),
                    {
                        "username": "newperson",
                        "email": "new@example.invalid",
                        "password": password,
                    },
                    format="json",
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("password", response.data["error"]["details"])
                self.assertFalse(
                    User.objects.filter(email="new@example.invalid").exists()
                )
        response = client.post(
            url("register"),
            {
                "username": "newperson",
                "email": "new@example.invalid",
                "password": PASSWORD,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        user = User.objects.get(email="new@example.invalid")
        self.assertTrue(user.check_password(PASSWORD))
        self.assertEqual(
            set(response.data["user"]), {"id", "username", "email", "profile"}
        )
        raw = response.cookies[COOKIE].value
        self.assert_no_refresh_json(response, raw)
        self.assertEqual(OutstandingToken.objects.get(user=user).token, "")

    def test_registration_rejects_mass_assignment_and_duplicate_identity(self):
        client = self.csrf_client()
        for extras in (
            {"is_staff": True},
            {"id": str(self.other.pk)},
            {"is_superuser": True},
            {"profile": {"user": str(self.other.pk)}},
        ):
            response = client.post(
                url("register"),
                {
                    "username": "extra",
                    "email": "extra@example.invalid",
                    "password": PASSWORD,
                    **extras,
                },
                format="json",
            )
            self.assertEqual(response.status_code, 400)
            self.assertEqual(User.objects.count(), 3)
        response = client.post(
            url("register"),
            {
                "username": self.user.username,
                "email": self.user.email,
                "password": PASSWORD,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_login_access_authentication_and_no_sensitive_output(self):
        client, response = self.signed_in()
        token = AccessToken(response.data["access"])
        self.assertEqual(token["user_id"], str(self.user.pk))
        self.assertEqual(token["exp"] - token["iat"], 300)
        self.assertEqual(response.data["expires_in"], 300)
        me = client.get(url("me"))
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.data["user"]["id"], str(self.user.pk))
        self.assertNotIn("password", json.dumps(me.data))
        self.assert_no_refresh_json(response, response.cookies[COOKIE].value)

    def test_inactive_bad_password_and_unknown_login_fail_without_sessions(
        self,
    ):
        client = self.csrf_client()
        for email, password in (
            (self.inactive.email, PASSWORD),
            (self.user.email, "incorrect"),
            ("absent@example.invalid", PASSWORD),
        ):
            response = client.post(
                url("login"),
                {
                    "email": email,
                    "password": password,
                },
                format="json",
            )
            self.assertEqual(response.status_code, 401)
            self.assertNotIn(COOKIE, response.cookies)
        self.assertFalse(OutstandingToken.objects.exists())

    def test_missing_invalid_expired_and_inactive_bearers_fail(self):
        client = self.csrf_client()
        self.assertEqual(client.get(url("me")).status_code, 401)
        expired = AccessToken.for_user(self.user)
        expired.set_exp(lifetime=timedelta(seconds=-1))
        inactive = AccessToken.for_user(self.user)
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        for raw in ("invalid", str(expired), str(inactive)):
            client.credentials(HTTP_AUTHORIZATION="Bearer " + raw)
            self.assertEqual(client.get(url("me")).status_code, 401)

    @override_settings(NEXUS_REFRESH_COOKIE_SECURE=True, DEBUG=True)
    def test_cookie_security_is_explicit_and_independent_of_debug(self):
        _, response = self.signed_in()
        cookie = response.cookies[COOKIE]
        self.assertTrue(cookie["secure"])
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")
        self.assertEqual(cookie["path"], "/api/v2/auth/")
        self.assertEqual(cookie["domain"], "")
        self.assertEqual(int(cookie["max-age"]), 7 * 24 * 3600)

    def test_anonymous_cookie_operations_require_csrf(self):
        client = APIClient(enforce_csrf_checks=True)
        bodies = {
            "register": {
                "email": "x@example.invalid",
                "username": "x",
                "password": PASSWORD,
            },
            "login": {"email": self.user.email, "password": PASSWORD},
            "refresh": {},
            "logout": {},
            "password-reset": {},
            "password-reset-confirm": {},
        }
        for name, body in bodies.items():
            response = client.post(url(name), body, format="json")
            self.assertEqual(response.status_code, 403, name)
        self.assertEqual(User.objects.count(), 3)
        self.assertFalse(OutstandingToken.objects.exists())

    def test_invalid_csrf_and_untrusted_origin_reject_without_rotation(self):
        client, _ = self.signed_in()
        raw = client.cookies[COOKIE].value
        client.defaults["HTTP_X_CSRFTOKEN"] = "wrong"
        self.assertEqual(
            client.post(url("refresh"), {}, format="json").status_code, 403
        )
        csrf = client.get(url("csrf")).data["csrf_token"]
        client.defaults["HTTP_X_CSRFTOKEN"] = csrf
        response = client.post(
            url("refresh"),
            {},
            format="json",
            HTTP_ORIGIN="https://attacker.example.invalid",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(client.cookies[COOKIE].value, raw)
        self.assertEqual(OutstandingToken.objects.count(), 1)
        self.assertFalse(BlacklistedToken.objects.exists())

    def test_refresh_rotates_and_rejects_replay_without_json_leak(self):
        client, _ = self.signed_in()
        original = client.cookies[COOKIE].value
        response = client.post(url("refresh"), {}, format="json")
        self.assertEqual(response.status_code, 200)
        replacement = client.cookies[COOKIE].value
        self.assertNotEqual(original, replacement)
        self.assert_no_refresh_json(response, replacement)
        self.assertEqual(BlacklistedToken.objects.count(), 1)
        self.assertEqual(OutstandingToken.objects.count(), 2)
        self.assertFalse(OutstandingToken.objects.exclude(token="").exists())
        client.cookies[COOKIE] = original
        response = client.post(url("refresh"), {}, format="json")
        self.assertEqual(response.status_code, 401)
        # An out-of-order failure must not delete a newer browser cookie.
        self.assertNotIn(COOKIE, response.cookies)
        self.assertEqual(OutstandingToken.objects.count(), 2)

    def test_refresh_rejects_missing_invalid_expired_and_legacy_tokens(self):
        client = self.csrf_client()
        expired = CookieRefreshToken.for_user(self.user)
        expired.set_exp(lifetime=timedelta(seconds=-1))
        for raw in (
            "",
            "broken",
            str(expired),
            str(RefreshToken.for_user(self.user)),
        ):
            client.cookies[COOKIE] = raw
            response = client.post(url("refresh"), {}, format="json")
            self.assertEqual(response.status_code, 401)

    def test_refresh_rejects_inactive_users(self):
        client, _ = self.signed_in()
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        self.assertEqual(
            client.post(url("refresh"), {}, format="json").status_code, 401
        )
        self.assertEqual(OutstandingToken.objects.count(), 1)

    def test_logout_revokes_only_current_session_and_clears_scoped_cookie(
        self,
    ):
        first, _ = self.signed_in()
        second, _ = self.signed_in()
        original = first.cookies[COOKIE].value
        response = first.post(url("logout"), {}, format="json")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.cookies[COOKIE]["path"], "/api/v2/auth/")
        self.assertTrue(response.cookies[COOKIE]["httponly"])
        self.assertEqual(response.cookies[COOKIE]["max-age"], 0)
        first.cookies[COOKIE] = original
        self.assertEqual(
            first.post(url("refresh"), {}, format="json").status_code, 401
        )
        self.assertEqual(
            second.post(url("refresh"), {}, format="json").status_code, 200
        )

    def test_logout_all_revokes_v2_and_legacy_refresh_sessions(self):
        first, _ = self.signed_in()
        second, _ = self.signed_in()
        legacy = str(RefreshToken.for_user(self.user))
        self.assertEqual(
            first.post(url("logout-all"), {}, format="json").status_code, 204
        )
        self.assertEqual(
            second.post(url("refresh"), {}, format="json").status_code, 401
        )
        response = APIClient().post(
            "/api/token/refresh/", {"refresh": legacy}, format="json"
        )
        self.assertEqual(response.status_code, 401)

    def test_logout_all_requires_bearer_and_csrf(self):
        client, _ = self.signed_in()
        client.defaults.pop("HTTP_X_CSRFTOKEN")
        self.assertEqual(
            client.post(url("logout-all"), {}, format="json").status_code, 403
        )
        self.assertFalse(BlacklistedToken.objects.exists())

    def test_current_account_profile_updates_are_owner_only(self):
        client, _ = self.signed_in()
        before = User.objects.values().get(pk=self.other.pk)
        response = client.patch(
            url("me"),
            {
                "username": "updated-v2",
                "profile": {
                    "bio": "Private biography",
                    "location": "Addis Ababa",
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["user"]["username"], "updated-v2")
        self.assertEqual(
            UserProfile.objects.get(user=self.user).bio, "Private biography"
        )
        self.assertEqual(User.objects.values().get(pk=self.other.pk), before)
        self.assertEqual(
            client.get(url("me") + str(self.other.pk) + "/").status_code, 404
        )

    def test_account_allowlist_rejects_identity_privileges_and_nested_owner(
        self,
    ):
        client, _ = self.signed_in()
        before = list(User.objects.order_by("pk").values())
        for field in (
            "id",
            "email",
            "password",
            "is_staff",
            "is_superuser",
            "is_active",
            "groups",
            "user_permissions",
            "date_joined",
        ):
            response = client.patch(
                url("me"), {field: "forbidden"}, format="json"
            )
            self.assertEqual(response.status_code, 400, field)
        for field in ("user", "id", "profile_picture", "last_seen"):
            response = client.patch(
                url("me"), {"profile": {field: "forbidden"}}, format="json"
            )
            self.assertEqual(response.status_code, 400, field)
        self.assertEqual(list(User.objects.order_by("pk").values()), before)
        self.assertFalse(UserProfile.objects.exists())

    def test_duplicate_username_rejection_leaves_profile_unchanged(self):
        client, _ = self.signed_in()
        response = client.patch(
            url("me"),
            {
                "username": self.other.username,
                "profile": {"bio": "rejected"},
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(UserProfile.objects.exists())

    def test_password_change_validates_current_and_new_password(self):
        client, _ = self.signed_in()
        for current, new in (("wrong", NEW_PASSWORD), (PASSWORD, "12345678")):
            response = client.post(
                url("password-change"),
                {
                    "current_password": current,
                    "new_password": new,
                },
                format="json",
            )
            self.assertEqual(response.status_code, 400)
            self.user.refresh_from_db()
            self.assertTrue(self.user.check_password(PASSWORD))
            self.assertFalse(BlacklistedToken.objects.exists())

    def test_password_change_revokes_all_existing_refresh_sessions(self):
        client, _ = self.signed_in()
        other_session, _ = self.signed_in()
        legacy = str(RefreshToken.for_user(self.user))
        response = client.post(
            url("password-change"),
            {
                "current_password": PASSWORD,
                "new_password": NEW_PASSWORD,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 204)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW_PASSWORD))
        self.assertEqual(
            other_session.post(url("refresh"), {}, format="json").status_code,
            401,
        )
        self.assertEqual(
            APIClient()
            .post("/api/token/refresh/", {"refresh": legacy}, format="json")
            .status_code,
            401,
        )
        # The approved auth_version fence also revokes existing access JWTs.
        self.assertEqual(client.get(url("me")).status_code, 401)

    def test_legacy_registration_and_token_contracts_remain_compatible(self):
        client = APIClient()
        registered = client.post(
            "/api/accounts/register/",
            {
                "email": "legacy@example.invalid",
                "username": "legacy",
                "password": PASSWORD,
            },
            format="json",
        )
        self.assertEqual(registered.status_code, 201)
        self.assertEqual(set(registered.data), {"username", "email"})
        response = client.post(
            "/api/token/",
            {
                "email": self.user.email,
                "password": PASSWORD,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data), {"access", "refresh"})
        refreshed = client.post(
            "/api/token/refresh/",
            {
                "refresh": response.data["refresh"],
            },
            format="json",
        )
        self.assertEqual(refreshed.status_code, 200)
        self.assertEqual(set(refreshed.data), {"access"})
        client.credentials(
            HTTP_AUTHORIZATION="Bearer " + refreshed.data["access"]
        )
        self.assertEqual(client.get("/api/polls/").status_code, 200)

    def test_v2_refresh_cannot_be_exchanged_at_legacy_json_endpoint(self):
        client, _ = self.signed_in()
        raw = client.cookies[COOKIE].value
        response = APIClient().post(
            "/api/token/refresh/", {"refresh": raw}, format="json"
        )
        self.assertEqual(response.status_code, 401)
        self.assertNotIn(raw, json.dumps(response.data))

    def test_cookie_alone_never_authenticates_account_access(self):
        client, _ = self.signed_in()
        client.credentials()
        self.assertEqual(client.get(url("me")).status_code, 401)

    def test_login_throttle_ignores_spoofed_ips_and_account_existence(self):
        client = self.csrf_client()
        for index in range(10):
            response = client.post(
                url("login"),
                {
                    "email": "missing@example.invalid",
                    "password": "wrong",
                },
                format="json",
                HTTP_X_FORWARDED_FOR=f"203.0.113.{index}",
            )
            self.assertEqual(response.status_code, 401)
        response = client.post(
            url("login"),
            {
                "email": self.user.email,
                "password": PASSWORD,
            },
            format="json",
            HTTP_X_FORWARDED_FOR="203.0.113.99",
        )
        self.assertEqual(response.status_code, 429)

    def test_cookie_expiration_matches_outstanding_expiry(self):
        client, response = self.signed_in()
        raw = client.cookies[COOKIE].value
        token = CookieRefreshToken(raw)
        record = OutstandingToken.objects.get(jti=token["jti"])
        self.assertLessEqual(
            abs(record.expires_at - timezone.now()), timedelta(days=7)
        )
        self.assertGreater(record.expires_at, timezone.now())
        self.assert_no_refresh_json(response, raw)

    def test_non_object_payloads_are_validation_errors_without_writes(self):
        client, _ = self.signed_in()
        for name, method, body in (
            ("register", "post", [{"id": "invalid"}]),
            ("login", "post", [{"email": "invalid"}]),
            ("me", "patch", [{"username": "invalid"}]),
            ("me", "patch", {"profile": [{"user": "invalid"}]}),
        ):
            response = getattr(client, method)(url(name), body, format="json")
            self.assertEqual(response.status_code, 400)
        self.assertEqual(User.objects.count(), 3)
        self.assertFalse(UserProfile.objects.exists())

    @override_settings(NEXUS_REFRESH_COOKIE_SECURE=True)
    def test_https_csrf_checks_accept_same_origin_and_reject_insecure_referer(
        self,
    ):
        client = APIClient(enforce_csrf_checks=True)
        bootstrap = client.get(url("csrf"), secure=True)
        client.defaults["HTTP_X_CSRFTOKEN"] = bootstrap.data["csrf_token"]
        response = client.post(
            url("login"),
            {"email": self.user.email, "password": PASSWORD},
            format="json",
            secure=True,
            HTTP_ORIGIN="https://testserver",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.cookies[COOKIE]["secure"])
        client.defaults["HTTP_X_CSRFTOKEN"] = response.data["csrf_token"]
        response = client.post(
            url("refresh"),
            {},
            format="json",
            secure=True,
            HTTP_REFERER="https://testserver/poll",
        )
        self.assertEqual(response.status_code, 200)
        raw = client.cookies[COOKIE].value
        response = client.post(
            url("refresh"),
            {},
            format="json",
            secure=True,
            HTTP_REFERER="http://testserver/poll",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(client.cookies[COOKIE].value, raw)
