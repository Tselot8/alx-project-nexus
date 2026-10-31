"""Nested and direct option route authorization."""

import uuid

from django.test import TestCase
from django.urls import reverse

from polls.models import Vote
from .test_poll_permissions import SecurityFixtures


class OptionPermissionTests(SecurityFixtures, TestCase):
    def option_url(self, poll):
        return reverse(
            "option-update-delete", args=[self.options[poll.pk][0].pk]
        )

    def test_public_option_reads_and_private_option_hiding(self):
        for user in (None, self.other, self.staff):
            client = self.client_for(user)
            self.assertEqual(
                client.get(self.option_url(self.public)).status_code, 200
            )
            self.reject(client, "get", self.option_url(self.private), 404)
        response = self.client_for(self.owner).get(
            self.option_url(self.private)
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])

    def test_non_owner_cannot_mutate_direct_options_or_delete_votes(self):
        option = self.options[self.public.pk][0]
        Vote.objects.create(user=self.owner, poll=self.public, option=option)
        option.votes_count = 1
        option.save(update_fields=["votes_count"])
        for user in (self.other, self.staff):
            for poll, code in ((self.public, 403), (self.private, 404)):
                for method in ("put", "patch", "delete"):
                    with self.subTest(user=user, poll=poll.pk, method=method):
                        self.reject(
                            self.client_for(user),
                            method,
                            self.option_url(poll),
                            code,
                            {"option_text": "Unauthorized"},
                        )

    def test_nested_create_requires_current_parent_ownership(self):
        for user in (self.other, self.staff):
            for poll, code in ((self.public, 403), (self.private, 404)):
                self.reject(
                    self.client_for(user),
                    "post",
                    reverse("option-create", args=[poll.pk]),
                    code,
                    {"option_text": "Unauthorized"},
                )

    def test_guest_option_mutations_require_authentication(self):
        for poll in (self.public, self.private):
            self.reject(
                self.client,
                "post",
                reverse("option-create", args=[poll.pk]),
                401,
                {"option_text": "Unauthorized"},
            )
            for method in ("put", "patch", "delete"):
                self.reject(self.client, method, self.option_url(poll), 401)

    def test_creator_can_manage_public_and_private_options(self):
        client = self.client_for(self.owner)
        for poll in (self.public, self.private):
            response = client.post(
                reverse("option-create", args=[poll.pk]),
                {"option_text": "Third"},
                format="json",
            )
            self.assertEqual(response.status_code, 201)
            if not poll.is_public:
                self.assertIn("no-store", response["Cache-Control"])
            url = reverse("option-update-delete", args=[response.data["id"]])
            for method in ("put", "patch"):
                response = getattr(client, method)(
                    url, {"option_text": "Renamed"}, format="json"
                )
                self.assertEqual(response.status_code, 200)
            self.assertEqual(client.delete(url).status_code, 204)

    def test_missing_option_and_parent_return_404(self):
        self.reject(
            self.client_for(self.owner),
            "post",
            reverse("option-create", args=[uuid.uuid4()]),
            404,
            {"option_text": "Missing"},
        )
        url = reverse("option-update-delete", args=[uuid.uuid4()])
        for method in ("get", "put", "patch", "delete"):
            self.reject(self.client_for(self.owner), method, url, 404)
