"""Account admin cannot revert credential epochs or leave reset JWTs valid."""

from types import SimpleNamespace
from unittest.mock import patch

from django.contrib import admin
from django.test import RequestFactory, TestCase
from django.urls import reverse
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.test import APIClient

from accounts.authentication import VersionedRefreshToken
from accounts.models import User
from accounts.test_v2_auth import NEW_PASSWORD, PASSWORD
from accounts.v2_services import (
    CookieRefreshToken,
    change_password,
    refresh_session,
)


class AccountAdminSecurityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(
            email="admin-target@example.invalid",
            username="admin-target",
            password=PASSWORD,
        )
        cls.administrator = User.objects.create_superuser(
            email="admin@example.invalid",
            username="administrator",
            password=PASSWORD,
        )

    def test_admin_password_change_revokes_legacy_and_v2_tokens(self):
        legacy = VersionedRefreshToken.for_user(self.owner)
        access = str(legacy.access_token)
        refresh = str(legacy)
        cookie = str(CookieRefreshToken.for_user(self.owner))
        self.client.force_login(self.administrator)
        response = self.client.post(
            reverse(
                "admin:auth_user_password_change", args=[self.owner.pk]
            ),
            {"password1": NEW_PASSWORD, "password2": NEW_PASSWORD},
        )
        self.assertEqual(response.status_code, 302)
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.auth_version, 2)
        self.assertTrue(self.owner.check_password(NEW_PASSWORD))
        api = APIClient()
        api.credentials(HTTP_AUTHORIZATION="Bearer " + access)
        self.assertEqual(api.get("/api/v2/auth/me/").status_code, 401)
        self.assertEqual(
            APIClient()
            .post("/api/token/refresh/", {"refresh": refresh}, format="json")
            .status_code,
            401,
        )
        with self.assertRaises(AuthenticationFailed):
            refresh_session(cookie)

    def test_stale_admin_save_preserves_new_password_and_auth_version(self):
        stale = User.objects.get(pk=self.owner.pk)
        change_password(self.owner, PASSWORD, NEW_PASSWORD)
        stale.username = "renamed-by-admin"
        request = RequestFactory().post("/admin/accounts/user/")
        request.user = self.administrator
        admin.site._registry[User].save_model(
            request,
            stale,
            SimpleNamespace(changed_data=["username"]),
            change=True,
        )
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.username, "renamed-by-admin")
        self.assertEqual(self.owner.auth_version, 2)
        self.assertTrue(self.owner.check_password(NEW_PASSWORD))

    def test_admin_form_excludes_auth_version(self):
        request = RequestFactory().get("/admin/accounts/user/")
        request.user = self.administrator
        form = admin.site._registry[User].get_form(request, self.owner)
        self.assertNotIn("auth_version", form.base_fields)

    def test_failed_admin_revocation_rolls_back_password_and_epoch(self):
        form = admin.site._registry[User].change_password_form(
            self.owner,
            {"password1": NEW_PASSWORD, "password2": NEW_PASSWORD},
        )
        self.assertTrue(form.is_valid(), form.errors)
        before = User.objects.values().get(pk=self.owner.pk)
        with patch(
            "accounts.v2_services.BlacklistedToken.objects.bulk_create",
            side_effect=RuntimeError("Simulated test-only storage failure"),
        ):
            with self.assertRaises(RuntimeError):
                form.save()
        self.assertEqual(User.objects.values().get(pk=self.owner.pk), before)
