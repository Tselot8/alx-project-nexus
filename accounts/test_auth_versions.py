"""Credential epochs close legacy and cookie-session revocation bypasses."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken
from rest_framework_simplejwt import serializers as jwt_serializers

from accounts.authentication import VersionedRefreshToken
from accounts.test_v2_auth import (
    AccountFixtures,
    COOKIE,
    NEW_PASSWORD,
    PASSWORD,
    url,
)
from accounts.v2_services import CookieRefreshToken, logout_all

User = get_user_model()


class VersionSecurityTests(AccountFixtures, TestCase):
    def bearer_client(self, raw):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION="Bearer " + raw)
        return client

    def test_versionless_tokens_are_compatible_only_at_version_one(self):
        old = RefreshToken.for_user(self.user)
        raw_refresh, raw_access = str(old), str(old.access_token)
        OutstandingToken.objects.filter(jti=old["jti"]).delete()
        self.assertEqual(
            self.bearer_client(raw_access).get(url("me")).status_code, 200
        )
        self.assertEqual(
            APIClient()
            .post(
                "/api/token/refresh/", {"refresh": raw_refresh}, format="json"
            )
            .status_code,
            200,
        )
        logout_all(self.user)
        self.assertEqual(
            self.bearer_client(raw_access).get(url("me")).status_code, 401
        )
        self.assertEqual(
            self.bearer_client(raw_access).get("/api/polls/").status_code, 401
        )
        self.assertEqual(
            APIClient()
            .post(
                "/api/token/refresh/", {"refresh": raw_refresh}, format="json"
            )
            .status_code,
            401,
        )
        self.user.refresh_from_db()
        self.assertEqual(self.user.auth_version, 2)

    def test_logout_all_revokes_versioned_v2_access_and_refresh(self):
        client, response = self.signed_in()
        raw_refresh = client.cookies[COOKIE].value
        raw_access = response.data["access"]
        self.assertEqual(AccessToken(raw_access)["auth_version"], 1)
        self.assertEqual(CookieRefreshToken(raw_refresh)["auth_version"], 1)
        self.assertEqual(
            client.post(url("logout-all"), {}, format="json").status_code,
            204,
        )
        # Even removing JTI blacklist fixtures cannot defeat the epoch check.
        BlacklistedToken.objects.all().delete()
        self.assertEqual(
            self.bearer_client(raw_access).get(url("me")).status_code, 401
        )
        client.cookies[COOKIE] = raw_refresh
        self.assertEqual(
            client.post(url("refresh"), {}, format="json").status_code, 401
        )
        self.assertEqual(OutstandingToken.objects.count(), 1)
        self.user.refresh_from_db()
        self.assertEqual(self.user.auth_version, 2)

    def test_password_change_revokes_legacy_access_and_new_logins_use_epoch(
        self,
    ):
        legacy = APIClient().post(
            "/api/token/",
            {
                "email": self.user.email,
                "password": PASSWORD,
            },
            format="json",
        )
        self.assertEqual(legacy.status_code, 200)
        self.assertEqual(set(legacy.data), {"access", "refresh"})
        self.assertEqual(AccessToken(legacy.data["access"])["auth_version"], 1)
        client, response = self.signed_in()
        raw_v2_access = response.data["access"]
        changed = client.post(
            url("password-change"),
            {
                "current_password": PASSWORD,
                "new_password": NEW_PASSWORD,
            },
            format="json",
        )
        self.assertEqual(changed.status_code, 204)
        self.user.refresh_from_db()
        self.assertEqual(self.user.auth_version, 2)
        for raw in (legacy.data["access"], raw_v2_access):
            self.assertEqual(
                self.bearer_client(raw).get(url("me")).status_code, 401
            )
        self.assertEqual(
            APIClient()
            .post(
                "/api/token/refresh/",
                {"refresh": legacy.data["refresh"]},
                format="json",
            )
            .status_code,
            401,
        )
        for name in ("legacy", "v2"):
            endpoint = "/api/token/" if name == "legacy" else url("login")
            active = self.csrf_client().post(
                endpoint,
                {
                    "email": self.user.email,
                    "password": NEW_PASSWORD,
                },
                format="json",
            )
            self.assertEqual(active.status_code, 200)
            self.assertEqual(
                AccessToken(active.data["access"])["auth_version"], 2
            )

    # SimpleJWT retains this settings object at import time. Change only its
    # configuration; all rotation, DB writes and HTTP handling remain real.
    @patch.object(jwt_serializers.api_settings, "ROTATE_REFRESH_TOKENS", True)
    @patch.object(
        jwt_serializers.api_settings, "BLACKLIST_AFTER_ROTATION", True
    )
    def test_legacy_rotation_cannot_upgrade_revoked_versionless_token(self):
        old = RefreshToken.for_user(self.user)
        raw = str(old)
        OutstandingToken.objects.filter(jti=old["jti"]).delete()
        rotated = APIClient().post(
            "/api/token/refresh/", {"refresh": raw}, format="json"
        )
        self.assertEqual(rotated.status_code, 200)
        self.assertEqual(set(rotated.data), {"access", "refresh"})
        self.assertFalse(OutstandingToken.objects.exclude(token="").exists())
        logout_all(self.user)
        # Remove blacklist to prove rejection uses the live user version.
        BlacklistedToken.objects.all().delete()
        before = OutstandingToken.objects.count()
        for raw in (raw, rotated.data["refresh"]):
            response = APIClient().post(
                "/api/token/refresh/", {"refresh": raw}, format="json"
            )
            self.assertEqual(response.status_code, 401)
        self.assertEqual(OutstandingToken.objects.count(), before)

    def test_invalid_versions_do_not_authenticate_or_refresh(self):
        for version in (0, -1, True, "1", None, 2):
            with self.subTest(version=version):
                token = VersionedRefreshToken.for_user(self.user)
                token["auth_version"] = version
                raw_access = str(token.access_token)
                response = self.bearer_client(raw_access).get(url("me"))
                self.assertEqual(response.status_code, 401)
                refreshed = APIClient().post(
                    "/api/token/refresh/",
                    {"refresh": str(token)},
                    format="json",
                )
                self.assertEqual(refreshed.status_code, 401)

    def test_inactive_user_cannot_refresh_through_legacy(self):
        token = VersionedRefreshToken.for_user(self.user)
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        response = APIClient().post(
            "/api/token/refresh/", {"refresh": str(token)}, format="json"
        )
        self.assertEqual(response.status_code, 401)

    def test_auth_version_is_not_client_editable_or_account_output(self):
        client, response = self.signed_in()
        self.assertNotIn("auth_version", response.data["user"])
        response = client.patch(
            url("me"), {"auth_version": 999}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        response = self.csrf_client().post(
            url("register"),
            {
                "username": "injected",
                "email": "injected@example.invalid",
                "password": PASSWORD,
                "auth_version": 999,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        response = APIClient().post(
            "/api/accounts/register/",
            {
                "username": "legacy-new",
                "email": "legacy-new@example.invalid",
                "password": PASSWORD,
                "auth_version": 999,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            User.objects.get(email="legacy-new@example.invalid").auth_version,
            1,
        )
        self.user.refresh_from_db()
        self.assertEqual(self.user.auth_version, 1)

    def test_failed_password_change_does_not_advance_epoch(self):
        client, _ = self.signed_in()
        before = User.objects.values().get(pk=self.user.pk)
        for old, new in (("wrong", NEW_PASSWORD), (PASSWORD, "12345678")):
            self.assertEqual(
                client.post(
                    url("password-change"),
                    {
                        "current_password": old,
                        "new_password": new,
                    },
                    format="json",
                ).status_code,
                400,
            )
            self.assertEqual(
                User.objects.values().get(pk=self.user.pk), before
            )
        self.assertFalse(BlacklistedToken.objects.exists())

    def test_model_and_database_enforce_noneditable_positive_version(self):
        self.assertFalse(User._meta.get_field("auth_version").editable)
        self.user.auth_version = 0
        with self.assertRaises(ValidationError):
            self.user.full_clean()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                User.objects.filter(pk=self.user.pk).update(auth_version=0)
        self.user.refresh_from_db()
        self.assertEqual(self.user.auth_version, 1)

    def test_legacy_invalid_refresh_retains_simplejwt_error_shape(self):
        response = APIClient().post(
            "/api/token/refresh/", {"refresh": "invalid"}, format="json"
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(set(response.data), {"detail", "code"})
        self.assertEqual(response.data["code"], "token_not_valid")

    def test_failed_revocation_rolls_back_password_and_version_together(self):
        from accounts.v2_services import change_password

        token = VersionedRefreshToken.for_user(self.user)
        before = User.objects.values().get(pk=self.user.pk)
        with patch(
            "accounts.v2_services.BlacklistedToken.objects.bulk_create",
            side_effect=RuntimeError(
                "Simulated test-only persistence failure"
            ),
        ):
            with self.assertRaises(RuntimeError):
                change_password(self.user, PASSWORD, NEW_PASSWORD)
        self.assertEqual(User.objects.values().get(pk=self.user.pk), before)
        self.assertEqual(
            self.bearer_client(str(token.access_token))
            .get(url("me"))
            .status_code,
            200,
        )
