"""Lifecycle, first-vote, version and legacy mutation security."""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from polls.models import AuditLog, Ballot, Poll, Vote
from .test_v2_discovery import BASE, EFixtures


class LifecycleTests(EFixtures, TestCase):
    def test_empty_draft_can_be_saved_but_not_published(self):
        client = self.auth()
        response = client.post(BASE + "polls/", {}, format="json")
        self.assertEqual(response.status_code, 201)
        poll = Poll.objects.get(pk=response.data["id"])
        self.assertEqual(
            (poll.status, poll.question, poll.version), ("draft", "", 1)
        )
        self.assertIs(poll.configuration_locked, False)
        self.assertFalse(poll.options.exists())
        self.rejected(client, "post", self.action(poll, "publish"), 400)

    def test_configuration_and_lifecycle_versions_and_explicit_reopening(self):
        client = self.auth()
        poll = self.new_draft(client)
        self.assertEqual(
            client.patch(
                self.detail(poll), {"description": "Updated"}, format="json"
            ).data["version"],
            2,
        )
        created = client.post(
            self.action(poll, "options"),
            {"option_text": "Maybe"},
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        option_url = self.action(poll, "options") + created.data["id"] + "/"
        self.assertEqual(
            client.patch(
                option_url, {"option_text": "Sometimes"}, format="json"
            ).status_code,
            200,
        )
        self.assertEqual(client.delete(option_url).status_code, 204)
        for action, body, version in (
            ("publish", {}, 6),
            ("close", {}, 7),
            ("reopen", {"expires_at": None}, 8),
            ("archive", {}, 9),
        ):
            response = client.post(
                self.action(poll, action), body, format="json"
            )
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data["version"], version)
        self.rejected(
            client,
            "post",
            self.action(poll, "reopen"),
            400,
            {"expires_at": None},
        )

    def test_publication_requires_distinct_nonblank_options_and_valid_limits(
        self,
    ):
        client = self.auth()
        cases = [
            {"question": ""},
            {"options": [{"option_text": "Only"}]},
            {"options": [{"option_text": "Yes"}, {"option_text": " yes "}]},
            {"options": [{"option_text": ""}, {"option_text": "No"}]},
            {"voting_mode": "multiple", "min_selections": 3},
            {
                "expires_at": (
                    timezone.now() - timedelta(seconds=1)
                ).isoformat()
            },
        ]
        for fields in cases:
            poll = self.new_draft(client, **fields)
            self.rejected(client, "post", self.action(poll, "publish"), 400)

    def test_invalid_input_and_protected_fields_leave_database_unchanged(self):
        client = self.auth()
        for field, value in (
            ("created_by", str(self.other.pk)),
            ("status", "published"),
            ("version", 999),
            ("configuration_locked", False),
            ("id", str(self.other.pk)),
            ("created_at", timezone.now().isoformat()),
            ("is_public", True),
            ("allow_multiple", True),
        ):
            self.rejected(client, "post", BASE + "polls/", 400, {field: value})
            self.rejected(
                client, "patch", self.detail(self.public), 400, {field: value}
            )
        for body in (
            {"min_selections": 2},
            {
                "voting_mode": "multiple",
                "min_selections": 3,
                "max_selections": 2,
            },
            {"min_selections": 2**63},
            {"options": [{"option_text": str(i)} for i in range(101)]},
        ):
            self.rejected(client, "post", BASE + "polls/", 400, body)
        self.rejected(
            client, "patch", self.detail(self.public), 400, {"options": []}
        )

    def test_nonowners_and_guests_cannot_manage_polls(self):
        for client in (self.auth(self.other), self.auth(self.staff)):
            for poll, code in ((self.public, 403), (self.private, 404)):
                self.rejected(
                    client,
                    "patch",
                    self.detail(poll),
                    code,
                    {"description": "forbidden"},
                )
                for action in ("publish", "close", "archive", "reopen"):
                    self.rejected(
                        client,
                        "post",
                        self.action(poll, action),
                        code,
                        {"expires_at": None} if action == "reopen" else {},
                    )
                self.rejected(client, "delete", self.detail(poll), code)
        for method, path in (
            ("post", BASE + "polls/"),
            ("patch", self.detail(self.public)),
            ("post", self.action(self.public, "close")),
        ):
            self.rejected(self.guest, method, path, 401)

    def test_archived_poll_and_options_are_immutable_through_both_apis(self):
        client = self.auth()
        option = self.option(self.archived)
        paths = (
            (self.detail(self.archived), {"description": "forbidden"}),
            (self.legacy(self.archived), {"description": "forbidden"}),
            (
                self.action(self.archived, "options") + str(option.pk) + "/",
                {"option_text": "forbidden"},
            ),
            (f"/api/polls/options/{option.pk}/", {"option_text": "forbidden"}),
        )
        for path, body in paths:
            self.rejected(client, "patch", path, 400, body)
            self.rejected(client, "delete", path, 400)
        for path in (
            self.action(self.archived, "options"),
            self.legacy(self.archived) + "options/",
        ):
            self.rejected(client, "post", path, 400, {"option_text": "No"})
        self.rejected(client, "post", self.vote_url(self.archived), 400)

    def test_only_verified_unvoted_drafts_can_be_deleted(self):
        client = self.auth()
        for poll in (self.public, self.private, self.closed, self.archived):
            for path in (self.detail(poll), self.legacy(poll)):
                self.rejected(client, "delete", path, 400)
        self.assertEqual(
            client.delete(self.detail(self.draft)).status_code, 204
        )
        unknown = Poll.objects.create(created_by=self.owner, status="draft")
        self.rejected(client, "delete", self.detail(unknown), 400)
        other = self.new_draft(client)
        self.assertEqual(client.delete(self.legacy(other)).status_code, 204)

    def test_expiration_and_date_edits_cannot_silently_reopen(self):
        client = self.auth()
        past = timezone.now() - timedelta(seconds=1)
        Poll.objects.filter(pk=self.public.pk).update(expires_at=past)
        self.rejected(
            self.auth(self.other), "post", self.vote_url(self.public), 400
        )
        self.assertEqual(
            self.guest.get(self.detail(self.public)).data["status"], "closed"
        )
        future = (timezone.now() + timedelta(days=1)).isoformat()
        response = client.patch(
            self.detail(self.public), {"expires_at": future}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.public.refresh_from_db()
        self.assertEqual(self.public.status, "closed")
        self.rejected(
            self.auth(self.other), "post", self.vote_url(self.public), 400
        )
        self.rejected(client, "post", self.action(self.public, "reopen"), 400)
        self.rejected(
            client,
            "post",
            self.action(self.public, "reopen"),
            400,
            {"expires_at": past.isoformat()},
        )
        response = client.post(
            self.action(self.public, "reopen"),
            {"expires_at": None},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "published")
        self.assertEqual(
            self.auth(self.other).post(self.vote_url(self.public)).status_code,
            200,
        )

    def test_first_vote_permanently_locks_configuration_and_options(self):
        client = self.auth()
        self.assertEqual(
            self.auth(self.other).post(self.vote_url(self.public)).status_code,
            200,
        )
        self.public.refresh_from_db()
        self.assertIs(self.public.configuration_locked, True)
        self.assertEqual(self.public.version, 2)
        for body in (
            {"question": "Changed"},
            {"visibility": "private"},
            {"voting_mode": "multiple"},
            {"results_visibility": "after_voting"},
            {"min_selections": 2},
            {"max_selections": 1},
        ):
            self.rejected(client, "patch", self.detail(self.public), 400, body)
        for body in (
            {"question": "Changed"},
            {"is_public": False},
            {"allow_multiple": True},
        ):
            for method in ("put", "patch"):
                self.rejected(
                    client, method, self.legacy(self.public), 400, body
                )
        option = self.option(self.public)
        for path in (
            self.action(self.public, "options") + str(option.pk) + "/",
            f"/api/polls/options/{option.pk}/",
        ):
            self.rejected(
                client, "patch", path, 400, {"option_text": "Changed"}
            )
            self.rejected(client, "delete", path, 400)
        self.rejected(
            client,
            "post",
            self.action(self.public, "options"),
            400,
            {"option_text": "Changed"},
        )
        # F native votes use ballots. Even removing all present participation
        # as a test fixture operation must never clear the permanent lock.
        Ballot.objects.filter(poll=self.public).delete()
        self.rejected(
            client,
            "patch",
            self.detail(self.public),
            400,
            {"question": "Still locked"},
        )
        response = client.patch(
            self.detail(self.public),
            {
                "description": "Permitted",
                "category": str(self.second_category.pk),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.data["configuration_locked"], True)

    def test_unknown_history_never_unlocks_and_audit_evidence_freezes_false(
        self,
    ):
        client = self.auth()
        Poll.objects.filter(pk=self.public.pk).update(
            configuration_locked=None
        )
        self.rejected(
            client,
            "patch",
            self.detail(self.public),
            400,
            {"question": "Unsafe"},
        )
        self.assertEqual(
            client.patch(
                self.detail(self.public),
                {"description": "Safe"},
                format="json",
            ).status_code,
            200,
        )
        self.public.refresh_from_db()
        self.assertIsNone(self.public.configuration_locked)
        AuditLog.objects.create(
            user=self.owner,
            action="Voted on poll",
            target_type="Poll",
            target_id=self.public.pk,
        )
        self.assertEqual(
            client.patch(
                self.detail(self.public),
                {"description": "History confirmed"},
                format="json",
            ).status_code,
            200,
        )
        self.public.refresh_from_db()
        self.assertIs(self.public.configuration_locked, True)
        AuditLog.objects.create(
            user=self.owner,
            action="Changed vote on poll",
            target_type="Poll",
            target_id=self.private.pk,
        )
        self.rejected(
            client,
            "patch",
            self.detail(self.private),
            400,
            {"visibility": "public"},
        )
        self.assertEqual(
            client.patch(
                self.detail(self.private),
                {"description": "Safe"},
                format="json",
            ).status_code,
            200,
        )
        self.private.refresh_from_db()
        self.assertIs(self.private.configuration_locked, True)

    def test_cross_poll_historical_vote_also_protects_option_parent(self):
        Vote.objects.create(
            user=self.other, poll=self.private, option=self.option(self.public)
        )
        self.rejected(
            self.auth(),
            "patch",
            self.detail(self.public),
            400,
            {"question": "Unsafe"},
        )

    def test_option_parent_and_counter_assignment_are_rejected(self):
        client = self.auth()
        option = self.option(self.public)
        endpoint = self.action(self.public, "options") + str(option.pk) + "/"
        for body in (
            {"poll": str(self.private.pk)},
            {"votes_count": 99},
            {"id": str(option.pk)},
            {"position": 0},
        ):
            self.rejected(client, "patch", endpoint, 400, body)
        wrong = self.action(self.private, "options") + str(option.pk) + "/"
        self.rejected(client, "patch", wrong, 404, {"option_text": "No"})

    def test_bounded_multiple_choice_requires_f_and_does_not_partially_vote(
        self,
    ):
        Poll.objects.filter(pk=self.public.pk).update(
            allow_multiple=True, min_selections=2, max_selections=2
        )
        self.rejected(
            self.auth(self.other), "post", self.vote_url(self.public), 400
        )
        self.assert_no_ballots()

    def test_legacy_publication_validation_and_closed_draft_voting(self):
        client = self.auth()
        self.rejected(
            client,
            "post",
            "/api/polls/",
            400,
            {
                "question": "Invalid?",
                "options": [{"option_text": "Only"}],
            },
        )
        for poll in (self.closed, self.archived):
            self.rejected(
                self.auth(self.other), "post", self.vote_url(poll), 400
            )
        self.rejected(
            self.auth(),
            "post",
            self.vote_url(self.draft, self.option(self.public)),
            404,
        )

    def test_noop_patch_does_not_advance_version(self):
        response = self.auth().patch(
            self.detail(self.public),
            {"question": self.public.question},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["version"], 1)
