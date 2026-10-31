"""Shared E fixtures: fresh polls have verified, never-voted history."""

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.authentication import VersionedRefreshToken
from accounts.models import User
from polls.models import (
    AuditLog,
    Ballot,
    BallotSelection,
    Category,
    Option,
    Poll,
    PollShareToken,
    Vote,
)

BASE = "/api/v2/"


class EFixtures:
    @classmethod
    def make_data(cls):
        cls.owner = User.objects.create_user(
            email="e-owner@example.invalid",
            username="e-owner",
            password="M8!maple-horizon-572",
        )
        cls.other = User.objects.create_user(
            email="e-other@example.invalid",
            username="e-other",
            password="M8!maple-horizon-572",
        )
        cls.staff = User.objects.create_superuser(
            email="e-admin@example.invalid",
            username="e-admin",
            password="M8!maple-horizon-572",
        )
        cls.category = Category.objects.create(name="General")
        cls.second_category = Category.objects.create(name="Science")
        for kind, status, public in (
            ("public", "published", True),
            ("private", "published", False),
            ("draft", "draft", True),
            ("closed", "closed", True),
            ("archived", "archived", True),
        ):
            poll = Poll.objects.create(
                question="" if kind == "draft" else kind + " coffee?",
                description="Choose tea or coffee",
                created_by=cls.owner,
                status=status,
                is_public=public,
                category=cls.category,
                configuration_locked=False,
            )
            if kind != "draft":
                Option.objects.bulk_create(
                    [
                        Option(poll=poll, option_text="Tea"),
                        Option(poll=poll, option_text="Coffee"),
                    ]
                )
            setattr(cls, kind, poll)

    @classmethod
    def setUpTestData(cls):
        cls.make_data()

    def setUp(self):
        super().setUp()
        cache.clear()
        self.guest = APIClient()

    def auth(self, user=None):
        user = user or self.owner
        client = APIClient()
        token = str(VersionedRefreshToken.for_user(user).access_token)
        client.credentials(HTTP_AUTHORIZATION="Bearer " + token)
        return client

    def detail(self, poll):
        return BASE + f"polls/{poll.pk}/"

    def legacy(self, poll):
        return f"/api/polls/{poll.pk}/"

    def action(self, poll, action):
        return self.detail(poll) + action + "/"

    def option(self, poll):
        return poll.options.order_by("id").first()

    def vote_url(self, poll, option=None):
        option = option or self.option(poll)
        return self.legacy(poll) + f"vote/{option.pk}/"

    def state(self):
        return {
            "polls": list(Poll.objects.order_by("id").values()),
            "options": list(Option.objects.order_by("id").values()),
            "votes": list(Vote.objects.order_by("id").values()),
            "audit": list(AuditLog.objects.order_by("id").values()),
            "shares": list(
                PollShareToken.objects.order_by("poll_id").values()
            ),
        }

    def rejected(self, client, method, url, status, body=None, **extra):
        before = self.state()
        response = getattr(client, method)(
            url, body or {}, format="json", **extra
        )
        self.assertEqual(response.status_code, status, response.data)
        self.assertEqual(self.state(), before)
        return response

    def new_draft(self, client=None, **fields):
        client = client or self.auth()
        response = client.post(
            BASE + "polls/",
            {
                "question": "A new question?",
                "options": [{"option_text": "Yes"}, {"option_text": "No"}],
                **fields,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        return Poll.objects.get(pk=response.data["id"])

    def assert_no_ballots(self):
        self.assertFalse(Ballot.objects.exists())
        self.assertFalse(BallotSelection.objects.exists())


class DiscoveryTests(EFixtures, TestCase):
    def test_public_discovery_excludes_private_draft_and_archived(self):
        for client in (self.guest, self.auth(), self.auth(self.other)):
            for path in (BASE + "polls/", "/api/polls/"):
                response = client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data["count"], 2)
                self.assertEqual(
                    {row["id"] for row in response.data["results"]},
                    {str(self.public.pk), str(self.closed.pk)},
                )

    def test_search_category_sort_and_pagination_are_bounded_and_stable(self):
        self.closed.category = self.second_category
        self.closed.save(update_fields=["category"])
        for query in (
            "?q=PUBLIC",
            "?q=choose&category=" + str(self.category.pk),
        ):
            response = self.guest.get(BASE + "polls/" + query)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data["count"], 1)
            self.assertEqual(
                response.data["results"][0]["id"], str(self.public.pk)
            )
        first = self.guest.get(BASE + "polls/?page_size=1&sort=oldest")
        second = self.guest.get(BASE + "polls/?page_size=1&sort=oldest&page=2")
        self.assertEqual(first.data["count"], 2)
        self.assertTrue(first.data["next"])
        self.assertNotEqual(
            first.data["results"][0]["id"], second.data["results"][0]["id"]
        )
        for query in (
            "?page_size=101",
            "?page=0",
            "?sort=bad",
            "?status=archived",
            "?category=bad",
            "?q=" + "a" * 201,
        ):
            self.assertEqual(
                self.guest.get(BASE + "polls/" + query).status_code, 400
            )

    def test_empty_search_and_unknown_category(self):
        import uuid

        for query in ("?q=no-such-question", "?category=" + str(uuid.uuid4())):
            response = self.guest.get(BASE + "polls/" + query)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data["count"], 0)

    def test_mine_is_authenticated_and_contains_only_owned_all_states(self):
        foreign = Poll.objects.create(
            created_by=self.other,
            question="Foreign",
            is_public=False,
            status="draft",
            configuration_locked=False,
        )
        self.assertEqual(self.guest.get(BASE + "polls/mine/").status_code, 401)
        response = self.auth().get(BASE + "polls/mine/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 5)
        self.assertNotIn(
            str(foreign.pk), {p["id"] for p in response.data["results"]}
        )
        for status in ("draft", "archived"):
            response = self.auth().get(BASE + "polls/mine/?status=" + status)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data["count"], 1)

    def test_category_list_is_public_and_paginated(self):
        response = self.guest.get(BASE + "categories/?page_size=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(
            set(response.data["results"][0]), {"id", "name", "description"}
        )

    def test_public_details_and_options_have_no_counts_or_lock_side_channels(
        self,
    ):
        for poll in (self.public, self.closed, self.archived):
            response = self.guest.get(self.detail(poll))
            self.assertEqual(response.status_code, 200)
            for field in (
                "version",
                "configuration_locked",
                "configuration_editable",
            ):
                self.assertNotIn(field, response.data)
            for option in response.data["options"]:
                self.assertEqual(set(option), {"id", "option_text"})
            self.assertEqual(
                self.guest.head(self.detail(poll)).status_code, 200
            )
        own = self.auth().get(self.detail(self.public))
        self.assertEqual(own.data["version"], 1)

    def test_hidden_drafts_private_and_missing_resources_match(self):
        import uuid

        for client in (
            self.guest,
            self.auth(self.other),
            self.auth(self.staff),
        ):
            missing = client.get(BASE + f"polls/{uuid.uuid4()}/")
            for poll in (self.private, self.draft):
                response = client.get(self.detail(poll))
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.data, missing.data)
                self.assertEqual(
                    client.get(self.legacy(poll)).status_code, 404
                )
        for poll in (self.private, self.draft):
            self.assertEqual(
                self.auth().get(self.detail(poll)).status_code, 200
            )
