"""Legacy API remains on Vote storage; future metadata stays dormant."""

from django.contrib import admin
from django.test import RequestFactory, TestCase
from django.urls import reverse

from polls.models import Ballot, BallotSelection, Poll, PollShareToken, Vote
from .test_poll_permissions import SecurityFixtures

METADATA = {
    "status",
    "results_visibility",
    "min_selections",
    "max_selections",
    "version",
    "configuration_locked",
}


class SchemaCompatibilityTests(SecurityFixtures, TestCase):
    def assert_empty_new_tables(self):
        self.assertFalse(Ballot.objects.exists())
        self.assertFalse(BallotSelection.objects.exists())
        self.assertFalse(PollShareToken.objects.exists())

    def assert_legacy_defaults(self, poll):
        poll.refresh_from_db()
        self.assertEqual(poll.status, "published")
        self.assertEqual(poll.results_visibility, "immediate")
        self.assertEqual(poll.min_selections, 1)
        self.assertIsNone(poll.max_selections)
        self.assertEqual(poll.version, 1)
        self.assertIsNone(poll.configuration_locked)

    def test_legacy_create_ignores_unexposed_future_metadata(self):
        response = self.client_for(self.owner).post(
            reverse("poll-list-create"),
            {
                "question": "Legacy creation?",
                "options": [{"option_text": "Yes"}, {"option_text": "No"}],
                "status": "draft",
                "results_visibility": "after_closing",
                "min_selections": 0,
                "max_selections": 0,
                "version": 99,
                "configuration_locked": False,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        poll = Poll.objects.get(pk=response.data["id"])
        self.assert_legacy_defaults(poll)
        self.assertFalse(METADATA & set(response.data))
        self.assert_empty_new_tables()

    def test_future_metadata_is_not_writable_through_legacy_updates(self):
        for method in ("put", "patch"):
            response = getattr(self.client_for(self.owner), method)(
                self.detail(self.public),
                {
                    "question": "Legacy update?",
                    "status": "archived",
                    "results_visibility": "after_voting",
                    "min_selections": 5,
                    "max_selections": 8,
                    "version": 100,
                    "configuration_locked": False,
                },
                format="json",
            )
            self.assertEqual(response.status_code, 200)
            self.assert_legacy_defaults(self.public)
            self.assertFalse(METADATA & set(response.data))
        self.assert_empty_new_tables()

    def test_new_fields_are_absent_from_automatic_legacy_admin_form(self):
        request = RequestFactory().get("/admin/polls/poll/")
        request.user = self.staff
        form = admin.site._registry[Poll].get_form(request, obj=self.public)
        self.assertFalse(METADATA & set(form.base_fields))
        for name in METADATA:
            self.assertFalse(Poll._meta.get_field(name).editable)

    def test_legacy_vote_and_public_results_remain_vote_authoritative(self):
        option = self.options[self.public.pk][0]
        response = self.client_for(self.other).post(
            reverse("cast-vote", args=[self.public.pk, option.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Vote.objects.filter(poll=self.public).count(), 1)
        result = self.client.get(
            reverse("poll-results", args=[self.public.pk])
        )
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.data["total_votes"], 1)
        self.assert_legacy_defaults(self.public)
        self.assert_empty_new_tables()

    def test_legacy_deletion_and_private_visibility_are_preserved(self):
        option = self.options[self.public.pk][0]
        response = self.client_for(self.other).post(
            reverse("cast-vote", args=[self.public.pk, option.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.client_for(self.owner)
            .delete(self.detail(self.public))
            .status_code,
            204,
        )
        self.assertFalse(Vote.objects.exists())
        self.assertEqual(
            self.client_for(self.other)
            .get(self.detail(self.private))
            .status_code,
            404,
        )
        self.assert_empty_new_tables()

    def test_draft_storage_can_be_incomplete_without_legacy_field_changes(
        self,
    ):
        draft = Poll.objects.create(
            created_by=self.owner,
            question="",
            is_public=False,
            status="draft",
            configuration_locked=False,
        )
        self.assertEqual(draft.question, "")
        self.assertFalse(draft.options.exists())
        self.assertIs(draft.configuration_locked, False)
        names = {field.name for field in Poll._meta.fields}
        self.assertIn("is_public", names)
        self.assertIn("allow_multiple", names)
        self.assertNotIn("visibility", names)
        self.assertNotIn("voting_mode", names)
        self.assert_empty_new_tables()
