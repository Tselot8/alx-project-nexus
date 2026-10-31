"""Registration and real JWT regression tests."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

User = get_user_model()


class RegistrationSecurityTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.payload = {
            "username": "participant",
            "email": "participant@example.invalid",
            "password": "Test-only!Strong-Password-93",
        }

    def test_configured_password_validators_reject_weak_passwords(self):
        for index, password in enumerate(
            (
                "short",
                "password",
                "1234567890123",
                "participant2026",
            )
        ):
            with self.subTest(password_case=password):
                before = User.objects.count()
                response = self.client.post(
                    "/api/accounts/register/",
                    {
                        **self.payload,
                        "password": password,
                        "username": f"participant{index}",
                        "email": f"participant{index}@example.invalid",
                    },
                    format="json",
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("password", response.data)
                self.assertEqual(User.objects.count(), before)

    def test_registration_hashes_password_and_cannot_create_privileged_user(
        self,
    ):
        response = self.client.post(
            "/api/accounts/register/",
            {**self.payload, "is_staff": True, "is_superuser": True},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(set(response.data), {"username", "email"})
        user = User.objects.get(email=self.payload["email"])
        self.assertTrue(user.check_password(self.payload["password"]))
        self.assertNotEqual(user.password, self.payload["password"])
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_real_login_and_refresh_contract_remains_unchanged(self):
        User.objects.create_user(**self.payload)
        response = self.client.post(
            "/api/token/",
            {
                "email": self.payload["email"],
                "password": self.payload["password"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data), {"access", "refresh"})
        refreshed = self.client.post(
            "/api/token/refresh/",
            {
                "refresh": response.data["refresh"],
            },
            format="json",
        )
        self.assertEqual(refreshed.status_code, 200)
        self.assertIn("access", refreshed.data)
        self.assertEqual(
            self.client.post(
                "/api/token/",
                {
                    "email": self.payload["email"],
                    "password": "Wrong-Test-Password",
                },
                format="json",
            ).status_code,
            401,
        )

    def test_similarity_validation_uses_submitted_unsaved_user(self):
        before = User.objects.count()
        response = self.client.post(
            "/api/accounts/register/",
            {
                "username": "NovelIdentityForThisTestQ7",
                "email": "unrelated@example.invalid",
                "password": "NovelIdentityForThisTestQ7!",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("password", response.data)
        self.assertEqual(User.objects.count(), before)
