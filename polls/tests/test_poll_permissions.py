"""Legacy poll authorization regression tests and shared test fixtures."""

import uuid

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from polls.models import AuditLog, Option, Poll, Vote


class SecurityFixtures:
    def setUp(self):
        super().setUp()
        cache.clear()
        self.owner = User.objects.create_user(
            email="creator@example.invalid",
            username="creator",
            password="Test-only!Strong-Password-93",
        )
        self.other = User.objects.create_user(
            email="outsider@example.invalid",
            username="outsider",
            password="Test-only!Strong-Password-93",
        )
        self.staff = User.objects.create_user(
            email="staff@example.invalid",
            username="staff",
            password="Test-only!Strong-Password-93",
            is_staff=True,
            is_superuser=True,
        )
        self.inactive = User.objects.create_user(
            email="inactive@example.invalid",
            username="inactive",
            password="Test-only!Strong-Password-93",
            is_active=False,
        )
        self.public = Poll.objects.create(
            question="Public question?",
            created_by=self.owner,
            configuration_locked=False,  # Fresh, verified unvoted fixture.
        )
        self.private = Poll.objects.create(
            question="Private question?",
            created_by=self.owner,
            is_public=False,
            configuration_locked=False,  # Fresh, verified unvoted fixture.
        )
        self.options = {
            poll.pk: [
                Option.objects.create(poll=poll, option_text=text)
                for text in ("First", "Second")
            ]
            for poll in (self.public, self.private)
        }
        self.client = APIClient()

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def client_for(self, user=None):
        client = APIClient()
        if user is not None:
            token = str(RefreshToken.for_user(user).access_token)
            client.credentials(HTTP_AUTHORIZATION="Bearer " + token)
        return client

    def snapshot(self):
        return {
            "users": list(
                User.objects.order_by("pk").values(
                    "id",
                    "username",
                    "email",
                    "is_active",
                    "is_staff",
                    "is_superuser",
                )
            ),
            "polls": list(Poll.objects.order_by("pk").values()),
            "options": list(Option.objects.order_by("pk").values()),
            "votes": list(Vote.objects.order_by("pk").values()),
            "audit": list(AuditLog.objects.order_by("pk").values()),
        }

    def reject(self, client, method, url, code, payload=None):
        before = self.snapshot()
        response = getattr(client, method)(
            url, data=payload or {}, format="json"
        )
        self.assertEqual(response.status_code, code, response.data)
        self.assertEqual(self.snapshot(), before)
        return response

    def detail(self, poll):
        return reverse("poll-detail", args=[poll.pk])


class PollPermissionTests(SecurityFixtures, TestCase):
    def test_discovery_is_public_and_never_counts_private_polls(self):
        url = reverse("poll-list-create")
        for user in (None, self.owner, self.other, self.staff):
            with self.subTest(user=user):
                response = self.client_for(user).get(url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data["count"], 1)
                self.assertEqual(
                    [row["id"] for row in response.data["results"]],
                    [str(self.public.pk)],
                )

    def test_public_details_and_head_are_readable(self):
        for user in (None, self.other, self.owner, self.staff):
            for method in ("get", "head"):
                with self.subTest(user=user, method=method):
                    response = getattr(self.client_for(user), method)(
                        self.detail(self.public)
                    )
                    self.assertEqual(response.status_code, 200)

    def test_private_details_are_hidden_even_from_staff(self):
        for user in (None, self.other, self.staff):
            for method in ("get", "head"):
                with self.subTest(user=user, method=method):
                    self.reject(
                        self.client_for(user),
                        method,
                        self.detail(self.private),
                        404,
                    )
        response = self.client_for(self.owner).get(self.detail(self.private))
        self.assertEqual(response.status_code, 200)
        self.assertIn("private", response["Cache-Control"])
        self.assertIn("no-store", response["Cache-Control"])

    def test_non_owner_mutations_distinguish_public_and_private(self):
        for user in (self.other, self.staff):
            for poll, code in ((self.public, 403), (self.private, 404)):
                for method in ("put", "patch", "delete"):
                    with self.subTest(user=user, poll=poll.pk, method=method):
                        self.reject(
                            self.client_for(user),
                            method,
                            self.detail(poll),
                            code,
                            {"question": "Unauthorized"},
                        )

    def test_guest_cannot_create_or_mutate(self):
        self.reject(self.client, "post", reverse("poll-list-create"), 401)
        for poll in (self.public, self.private):
            for method in ("put", "patch", "delete"):
                self.reject(self.client, method, self.detail(poll), 401)

    def test_creator_can_create_edit_and_delete(self):
        client = self.client_for(self.owner)
        response = client.post(
            reverse("poll-list-create"),
            {
                "question": "Created privately?",
                "is_public": False,
                "options": [{"option_text": "Yes"}, {"option_text": "No"}],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        poll = Poll.objects.get(pk=response.data["id"])
        self.assertEqual(poll.created_by_id, self.owner.pk)
        self.assertIn("no-store", response["Cache-Control"])
        for method in ("put", "patch"):
            response = getattr(client, method)(
                self.detail(poll), {"question": "Updated?"}, format="json"
            )
            self.assertEqual(response.status_code, 200)
        before = self.snapshot()
        self.assertEqual(client.delete(self.detail(poll)).status_code, 400)
        self.assertEqual(self.snapshot(), before)
        # Ownership still permits deletion of a legitimately created draft.
        draft = client.post("/api/v2/polls/", {}, format="json")
        self.assertEqual(draft.status_code, 201)
        self.assertEqual(
            client.delete(
                "/api/v2/polls/" + draft.data["id"] + "/"
            ).status_code,
            204,
        )

    def test_missing_resources_are_not_found(self):
        url = reverse("poll-detail", args=[uuid.uuid4()])
        for user in (None, self.owner, self.other):
            self.reject(self.client_for(user), "get", url, 404)
        self.reject(self.client_for(self.owner), "patch", url, 404)

    def test_invalid_and_expired_bearer_tokens_are_rejected(self):
        invalid = self.client_for()
        invalid.credentials(HTTP_AUTHORIZATION="Bearer not-a-token")
        self.reject(invalid, "get", self.detail(self.public), 401)
        token = RefreshToken.for_user(self.owner).access_token
        token["exp"] = 0
        expired = self.client_for()
        expired.credentials(HTTP_AUTHORIZATION="Bearer " + str(token))
        self.reject(expired, "post", reverse("poll-list-create"), 401)

    def test_options_metadata_has_no_private_values_or_owner_choices(self):
        response = self.client_for(self.other).options(
            self.detail(self.private)
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("actions", response.data)
        self.assertNotIn(self.private.question, str(response.data))

    def test_hidden_and_missing_resources_have_identical_error_bodies(self):
        other = self.client_for(self.other)
        missing = uuid.uuid4()
        pairs = [
            (
                "get",
                self.detail(self.private),
                reverse("poll-detail", args=[missing]),
            ),
            (
                "patch",
                self.detail(self.private),
                reverse("poll-detail", args=[missing]),
            ),
            (
                "get",
                reverse("poll-results", args=[self.private.pk]),
                reverse("poll-results", args=[missing]),
            ),
            (
                "post",
                reverse("option-create", args=[self.private.pk]),
                reverse("option-create", args=[missing]),
            ),
            (
                "patch",
                reverse(
                    "option-update-delete",
                    args=[self.options[self.private.pk][0].pk],
                ),
                reverse("option-update-delete", args=[missing]),
            ),
            (
                "post",
                reverse(
                    "cast-vote",
                    args=[
                        self.private.pk,
                        self.options[self.private.pk][0].pk,
                    ],
                ),
                reverse("cast-vote", args=[missing, missing]),
            ),
        ]
        for method, hidden, absent in pairs:
            with self.subTest(method=method, path=hidden):
                hidden_response = self.reject(other, method, hidden, 404)
                absent_response = self.reject(other, method, absent, 404)
                self.assertEqual(hidden_response.data, absent_response.data)
