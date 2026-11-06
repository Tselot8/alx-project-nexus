"""Recovery delivery uses local capture only; tokens are never API output."""

from smtplib import SMTPException
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.test import APIClient

from accounts.test_v2_auth import (
    AccountFixtures,
    COOKIE,
    NEW_PASSWORD,
    PASSWORD,
    url,
)
from accounts.v2_services import recovery_tokens


class RecoveryDisabledTests(AccountFixtures, TestCase):
    def test_recovery_is_closed_until_explicitly_configured(self):
        client = self.csrf_client()
        for name in ("password-reset", "password-reset-confirm"):
            response = client.post(url(name), {}, format="json")
            self.assertEqual(response.status_code, 503)


@override_settings(
    NEXUS_PASSWORD_RESET_ENABLED=True,
    NEXUS_PASSWORD_RESET_ORIGIN="https://frontend.example.invalid",
    DEFAULT_FROM_EMAIL="noreply@example.invalid",
)
class RecoveryTests(AccountFixtures, TestCase):
    def link_fields(self):
        link = mail.outbox[-1].body.strip().splitlines()[-1]
        parsed = urlsplit(link)
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.netloc, "frontend.example.invalid")
        self.assertEqual(parsed.path, "/reset-password")
        self.assertEqual(parsed.query, "")
        query = parse_qs(parsed.fragment)
        return {"uid": query["uid"][0], "token": query["token"][0]}

    def test_request_is_generic_for_known_unknown_inactive_and_unusable(self):
        client = self.csrf_client()
        self.other.set_unusable_password()
        self.other.save(update_fields=["password"])
        bodies = []
        for email in (
            self.user.email,
            "absent@example.invalid",
            self.inactive.email,
            self.other.email,
        ):
            response = client.post(
                url("password-reset"), {"email": email}, format="json"
            )
            self.assertEqual(response.status_code, 202)
            bodies.append(response.data)
        self.assertTrue(all(body == bodies[0] for body in bodies))
        self.assertEqual(len(mail.outbox), 1)
        fields = self.link_fields()
        self.assertNotIn(fields["token"], str(bodies))
        self.assertNotIn(fields["uid"], str(bodies))

    def test_link_origin_never_comes_from_host_or_forwarded_headers(self):
        client = self.csrf_client()
        response = client.post(
            url("password-reset"),
            {"email": self.user.email},
            format="json",
            HTTP_X_FORWARDED_HOST="attacker.example.invalid",
        )
        self.assertEqual(response.status_code, 202)
        self.link_fields()

    def test_reset_changes_password_and_revokes_v2_and_legacy_sessions(self):
        client, _ = self.signed_in()
        raw = client.cookies[COOKIE].value
        legacy = str(RefreshToken.for_user(self.user))
        response = client.post(
            url("password-reset"), {"email": self.user.email}, format="json"
        )
        self.assertEqual(response.status_code, 202)
        fields = self.link_fields()
        response = client.post(
            url("password-reset-confirm"),
            {
                **fields,
                "new_password": NEW_PASSWORD,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 204)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW_PASSWORD))
        self.assertEqual(self.user.auth_version, 2)
        self.assertEqual(client.get(url("me")).status_code, 401)
        client.cookies[COOKIE] = raw
        self.assertEqual(
            client.post(url("refresh"), {}, format="json").status_code, 401
        )
        self.assertEqual(
            APIClient()
            .post("/api/token/refresh/", {"refresh": legacy}, format="json")
            .status_code,
            401,
        )
        self.assertEqual(
            client.post(
                url("password-reset-confirm"),
                {**fields, "new_password": PASSWORD},
                format="json",
            ).status_code,
            400,
        )
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW_PASSWORD))

    def test_expired_reset_token_is_rejected_without_password_changes(self):
        client = self.csrf_client()
        past = timezone.now().replace(tzinfo=None) - timedelta(minutes=31)
        with patch.object(recovery_tokens, "_now", return_value=past):
            client.post(
                url("password-reset"),
                {"email": self.user.email},
                format="json",
            )
        fields = self.link_fields()
        response = client.post(
            url("password-reset-confirm"),
            {
                **fields,
                "new_password": NEW_PASSWORD,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))

    def test_invalid_uid_wrong_user_and_weak_password_are_rejected(self):
        client = self.csrf_client()
        client.post(
            url("password-reset"), {"email": self.user.email}, format="json"
        )
        fields = self.link_fields()
        for changes in (
            {"uid": "not-a-user"},
            {"token": "not-a-valid-token"},
            {"new_password": "12345678"},
        ):
            response = client.post(
                url("password-reset-confirm"),
                {
                    **fields,
                    "new_password": NEW_PASSWORD,
                    **changes,
                },
                format="json",
            )
            self.assertEqual(response.status_code, 400)
            self.user.refresh_from_db()
            self.assertTrue(self.user.check_password(PASSWORD))

    def test_reset_token_is_single_purpose(self):
        from django.contrib.auth.tokens import default_token_generator

        self.assertFalse(
            default_token_generator.check_token(
                self.user, recovery_tokens.make_token(self.user)
            )
        )
        self.assertFalse(
            recovery_tokens.check_token(
                self.user, default_token_generator.make_token(self.user)
            )
        )

    def test_delivery_failure_does_not_change_generic_response(self):
        client = self.csrf_client()
        with patch("accounts.v2_services.send_mail", side_effect=OSError):
            known = client.post(
                url("password-reset"),
                {"email": self.user.email},
                format="json",
            )
            unknown = client.post(
                url("password-reset"),
                {"email": "none@example.invalid"},
                format="json",
            )
        self.assertEqual(known.status_code, 202)
        self.assertEqual(known.data, unknown.data)

    def test_pre_d_untracked_legacy_refresh_is_revoked_after_reset(self):
        from rest_framework_simplejwt.token_blacklist.models import (
            OutstandingToken,
        )

        legacy = RefreshToken.for_user(self.user)
        raw = str(legacy)
        # Reproduce a token issued before the blacklist app existed.
        OutstandingToken.objects.filter(jti=legacy["jti"]).delete()
        client = self.csrf_client()
        client.post(
            url("password-reset"), {"email": self.user.email}, format="json"
        )
        fields = self.link_fields()
        response = client.post(
            url("password-reset-confirm"),
            {**fields, "new_password": NEW_PASSWORD},
            format="json",
        )
        self.assertEqual(response.status_code, 204)
        refreshed = APIClient().post(
            "/api/token/refresh/", {"refresh": raw}, format="json"
        )
        self.assertEqual(refreshed.status_code, 401)

    def test_smtp_failure_is_generic_silent_and_preserves_account(self):
        client = self.csrf_client()
        before = (self.user.password, self.user.auth_version)
        with patch(
            "accounts.v2_services.send_mail", side_effect=SMTPException
        ), self.assertNoLogs("accounts", level="WARNING"):
            known = client.post(
                url("password-reset"),
                {"email": self.user.email},
                format="json",
            )
            unknown = client.post(
                url("password-reset"),
                {"email": "missing@example.invalid"},
                format="json",
            )
        self.assertEqual(known.status_code, 202)
        self.assertEqual(known.data, unknown.data)
        self.user.refresh_from_db()
        self.assertEqual(before, (self.user.password, self.user.auth_version))
