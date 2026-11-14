"""Actual HTTP signup gates, unchanged sessions, and isolated defaults."""

import os
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)

from accounts.models import UserProfile
from accounts.test_v2_auth import AccountFixtures, PASSWORD, User, url
from alx_project_nexus import settings as shared_settings


class RegistrationGateTests(AccountFixtures, TestCase):
    def snapshot(self):
        return tuple(
            model.objects.count()
            for model in (
                User,
                UserProfile,
                OutstandingToken,
                BlacklistedToken,
            )
        )

    def payload(self, suffix):
        return {
            "email": f"registration-{suffix}@example.invalid",
            "username": f"registration-{suffix}",
            "password": PASSWORD,
        }

    @override_settings(NEXUS_REGISTRATION_ENABLED=False)
    def test_disabled_routes_reject_without_queries_or_side_effects(
        self,
    ):
        for path in ("/api/accounts/register/", url("register")):
            client = self.csrf_client()
            before = self.snapshot()
            with self.subTest(path=path), self.assertNumQueries(0):
                response = client.post(
                    path, self.payload("blocked"), format="json"
                )
                self.assertEqual(response.status_code, 503)
            self.assertEqual(self.snapshot(), before)
            self.assertNotIn("nexus_v2_refresh_token", response.cookies)
            self.assertIn("no-store", response["Cache-Control"])
            if path == url("register"):
                self.assertEqual(
                    response.data["error"]["code"], "registration_disabled"
                )
            else:
                self.assertEqual(
                    response.data["detail"].code, "registration_disabled"
                )

    @override_settings(NEXUS_REGISTRATION_ENABLED=False)
    def test_disabled_gate_precedes_payload_validation_and_identity_lookup(
        self,
    ):
        for path in ("/api/accounts/register/", url("register")):
            client = self.csrf_client()
            before = self.snapshot()
            for body in (
                {},
                {"email": self.user.email},
                {"is_superuser": True},
            ):
                with self.subTest(
                    path=path, body_kind=list(body)
                ), self.assertNumQueries(0):
                    self.assertEqual(
                        client.post(path, body, format="json").status_code, 503
                    )
            self.assertEqual(self.snapshot(), before)

    @override_settings(NEXUS_REGISTRATION_ENABLED=True)
    def test_enabled_routes_keep_existing_success_contracts(self):
        for suffix, path in (
            ("legacy", "/api/accounts/register/"),
            ("v2", url("register")),
        ):
            client = self.csrf_client()
            payload = self.payload(suffix)
            response = client.post(path, payload, format="json")
            self.assertEqual(response.status_code, 201)
            account = User.objects.get(email=payload["email"])
            self.assertTrue(account.check_password(PASSWORD))
            self.assertFalse(account.is_staff or account.is_superuser)
            if suffix == "legacy":
                self.assertEqual(set(response.data), {"email", "username"})
            else:
                self.assertEqual(
                    set(response.data),
                    {"user", "access", "expires_in", "csrf_token"},
                )
                self.assertNotIn("refresh", response.data)
                self.assertTrue(
                    response.cookies["nexus_v2_refresh_token"]["httponly"]
                )

    def test_gate_can_be_enabled_without_code_changes(self):
        client = self.csrf_client()
        for path, suffix in (
            ("/api/accounts/register/", "toggle-old"),
            (url("register"), "toggle-v2"),
        ):
            with override_settings(NEXUS_REGISTRATION_ENABLED=False):
                self.assertEqual(
                    client.post(
                        path, self.payload(suffix), format="json"
                    ).status_code,
                    503,
                )
            with override_settings(NEXUS_REGISTRATION_ENABLED=True):
                self.assertEqual(
                    client.post(
                        path, self.payload(suffix), format="json"
                    ).status_code,
                    201,
                )
            # V2 successful registration rotates the CSRF token.
            client = self.csrf_client()

    def test_v2_csrf_remains_required_in_both_gate_states(self):
        from rest_framework.test import APIClient

        for enabled in (False, True):
            before = self.snapshot()
            with override_settings(NEXUS_REGISTRATION_ENABLED=enabled):
                response = APIClient(enforce_csrf_checks=True).post(
                    url("register"),
                    self.payload("csrf"),
                    format="json",
                )
            self.assertEqual(response.status_code, 403)
            self.assertEqual(self.snapshot(), before)

    @override_settings(NEXUS_REGISTRATION_ENABLED=False)
    def test_existing_v2_login_profile_refresh_and_logout_are_unchanged(self):
        client, _ = self.signed_in()
        self.assertEqual(client.get(url("me")).status_code, 200)
        response = client.patch(
            url("me"), {"profile": {"bio": "Gate regression"}}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["user"]["profile"]["bio"], "Gate regression"
        )
        self.assertEqual(
            client.post(url("refresh"), {}, format="json").status_code, 200
        )
        self.assertEqual(
            client.post(url("logout"), {}, format="json").status_code, 204
        )

    @override_settings(NEXUS_REGISTRATION_ENABLED=False)
    def test_existing_legacy_login_and_refresh_are_unchanged(self):
        client = self.csrf_client()
        response = client.post(
            "/api/token/",
            {"email": self.user.email, "password": PASSWORD},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data), {"access", "refresh"})
        self.assertEqual(
            client.post(
                "/api/token/refresh/",
                {"refresh": response.data["refresh"]},
                format="json",
            ).status_code,
            200,
        )


class RegistrationDefaultsTests(SimpleTestCase):
    def test_defaults_closed_for_production_and_open_for_isolated_profiles(
        self,
    ):
        for isolated in (False, True):
            with self.subTest(isolated=isolated), patch.dict(
                os.environ, {}, clear=True
            ), patch.object(shared_settings, "_ISOLATED", isolated):
                self.assertEqual(
                    shared_settings._registration_settings(),
                    {"NEXUS_REGISTRATION_ENABLED": isolated},
                )

    def test_explicit_configuration_overrides_either_default(self):
        for isolated in (False, True):
            for value, expected in (("true", True), ("false", False)):
                with self.subTest(isolated=isolated, value=value), patch.dict(
                    os.environ,
                    {"NEXUS_REGISTRATION_ENABLED": value},
                    clear=True,
                ), patch.object(shared_settings, "_ISOLATED", isolated):
                    self.assertEqual(
                        shared_settings._registration_settings()[
                            "NEXUS_REGISTRATION_ENABLED"
                        ],
                        expected,
                    )

    def test_invalid_values_fail_without_echoing_configuration(self):
        for value in ("", "yes", "1", "synthetic-private-value"):
            with patch.dict(
                os.environ, {"NEXUS_REGISTRATION_ENABLED": value}, clear=True
            ):
                with self.assertRaises(ImproperlyConfigured) as error:
                    shared_settings._registration_settings()
            self.assertIn("NEXUS_REGISTRATION_ENABLED", str(error.exception))
            if value:
                self.assertNotIn(value, str(error.exception))
