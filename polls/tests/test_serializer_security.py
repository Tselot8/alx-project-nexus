"""Protected metadata, HTML privacy, and atomic nested creation."""

from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from polls.models import Option, Vote
from polls.serializers import PollCreateSerializer
from .test_poll_permissions import SecurityFixtures


class SerializerSecurityTests(SecurityFixtures, TestCase):
    def test_poll_metadata_rejected_on_creation_and_updates(self):
        values = {
            "id": str(self.private.pk),
            "created_by": str(self.other.pk),
            "created_at": "2000-01-01T00:00:00Z",
            "updated_at": "2000-01-01T00:00:00Z",
        }
        client = self.client_for(self.owner)
        for field, value in values.items():
            payload = {
                "question": "Valid?",
                field: value,
                "options": [{"option_text": "One"}, {"option_text": "Two"}],
            }
            self.reject(
                client, "post", reverse("poll-list-create"), 400, payload
            )
            for method in ("put", "patch"):
                response = self.reject(
                    client,
                    method,
                    self.detail(self.public),
                    400,
                    {"question": "Valid?", field: value},
                )
                self.assertIn(field, response.data)

    def test_nested_update_and_option_metadata_are_rejected(self):
        client = self.client_for(self.owner)
        for method in ("put", "patch"):
            self.reject(
                client,
                method,
                self.detail(self.public),
                400,
                {"question": "Valid?", "options": []},
            )
        option = self.options[self.public.pk][0]
        values = {
            "id": str(self.options[self.private.pk][0].pk),
            "poll": str(self.private.pk),
            "poll_id": str(self.private.pk),
            "votes_count": 99,
        }
        for field, value in values.items():
            for method in ("put", "patch"):
                self.reject(
                    client,
                    method,
                    reverse("option-update-delete", args=[option.pk]),
                    400,
                    {"option_text": "Valid", field: value},
                )
            self.reject(
                client,
                "post",
                reverse("option-create", args=[self.public.pk]),
                400,
                {"option_text": "Valid", field: value},
            )
            self.reject(
                client,
                "post",
                reverse("poll-list-create"),
                400,
                {
                    "question": "Valid?",
                    "options": [
                        {"option_text": "Valid", field: value},
                        {"option_text": "Other"},
                    ],
                },
            )

    def test_owner_choices_do_not_disclose_other_emails(self):
        response = self.client_for(self.owner).get(
            self.detail(self.public), HTTP_ACCEPT="text/html"
        )
        self.assertEqual(response.status_code, 200)
        for user in (self.other, self.staff, self.inactive):
            self.assertNotContains(response, user.email)

    def test_mode_change_rejected_after_votes_for_put_and_patch(self):
        Vote.objects.create(
            user=self.owner,
            poll=self.public,
            option=self.options[self.public.pk][0],
        )
        for method in ("put", "patch"):
            self.reject(
                self.client_for(self.owner),
                method,
                self.detail(self.public),
                400,
                {"question": self.public.question, "allow_multiple": True},
            )

    def test_mode_change_without_votes_remains_allowed(self):
        response = self.client_for(self.owner).patch(
            self.detail(self.public), {"allow_multiple": True}, format="json"
        )
        self.assertEqual(response.status_code, 200)

    def test_nested_creation_rolls_back_after_partial_database_failure(self):
        serializer = PollCreateSerializer(
            data={
                "question": "Atomic creation?",
                "options": [
                    {"option_text": "First"},
                    {"option_text": "Second"},
                ],
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        before = self.snapshot()
        original_create = Option.objects.create
        count = 0

        def fail_second(*args, **kwargs):
            nonlocal count
            count += 1
            if count == 2:
                raise RuntimeError("Simulated local write failure")
            return original_create(*args, **kwargs)

        with patch(
            "polls.serializers.Option.objects.create", side_effect=fail_second
        ):
            with self.assertRaises(RuntimeError):
                serializer.save(created_by=self.owner)
        self.assertEqual(self.snapshot(), before)
