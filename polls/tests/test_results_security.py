"""Results must enforce visibility and ignore stale payload caches."""

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from polls.views import cast_vote
from .test_poll_permissions import SecurityFixtures


class ResultsSecurityTests(SecurityFixtures, TestCase):
    def results(self, poll):
        return reverse("poll-results", args=[poll.pk])

    def test_public_results_are_anonymous_and_preserve_aggregate_schema(self):
        response = self.client.get(self.results(self.public))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(response.data),
            {
                "poll_id",
                "question",
                "options",
                "total_votes",
            },
        )
        self.assertEqual(
            set(response.data["options"][0]),
            {
                "id",
                "option_text",
                "votes_count",
                "total_votes",
            },
        )

    def test_private_results_ignore_warmed_cache_and_hide_existence(self):
        cache.set(
            f"poll_results:{self.private.pk}",
            {
                "poll_id": str(self.private.pk),
                "question": "Cached private",
                "options": [],
                "total_votes": 99,
            },
        )
        for user in (None, self.other, self.staff):
            self.reject(
                self.client_for(user), "get", self.results(self.private), 404
            )
        response = self.client_for(self.owner).get(self.results(self.private))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["total_votes"], 0)
        self.assertIn("no-store", response["Cache-Control"])

    def test_public_cache_is_not_trusted_and_options_are_live(self):
        cache.set(
            f"poll_results:{self.public.pk}",
            {
                "poll_id": str(self.public.pk),
                "question": "Stale",
                "options": [],
                "total_votes": 99,
            },
        )
        response = self.client.get(self.results(self.public))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["total_votes"], 0)
        self.assertEqual(len(response.data["options"]), 2)
        owner = self.client_for(self.owner)
        created = owner.post(
            reverse("option-create", args=[self.public.pk]),
            {"option_text": "Third"},
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        url = reverse("option-update-delete", args=[created.data["id"]])
        self.assertEqual(
            owner.patch(
                url, {"option_text": "Renamed"}, format="json"
            ).status_code,
            200,
        )
        response = self.client.get(self.results(self.public))
        self.assertEqual(len(response.data["options"]), 3)
        self.assertIn(
            "Renamed",
            [option["option_text"] for option in response.data["options"]],
        )
        self.assertEqual(owner.delete(url).status_code, 204)
        self.assertEqual(
            len(self.client.get(self.results(self.public)).data["options"]), 2
        )

    def test_visibility_change_revokes_access_even_with_old_cached_results(
        self,
    ):
        cache.set(f"poll_results:{self.public.pk}", {"total_votes": 99})
        response = self.client_for(self.owner).patch(
            self.detail(self.public), {"is_public": False}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        for user in (None, self.other, self.staff):
            client = self.client_for(user)
            self.reject(client, "get", self.detail(self.public), 404)
            self.reject(client, "get", self.results(self.public), 404)

    def test_result_counts_are_live_and_never_include_voter_identities(self):
        client = self.client_for(self.other)
        first, second = self.options[self.public.pk]
        cast_vote(self.other, self.public.pk, first.pk)
        self.assertEqual(
            client.get(self.results(self.public)).data["total_votes"], 1
        )
        cast_vote(self.other, self.public.pk, second.pk)
        response = client.get(self.results(self.public))
        mapping = {
            option["id"]: option["total_votes"]
            for option in response.data["options"]
        }
        self.assertEqual(mapping[str(first.pk)], 0)
        self.assertEqual(mapping[str(second.pk)], 1)
        for user in (self.owner, self.other):
            self.assertNotIn(user.email, str(response.data))
            self.assertNotIn(str(user.pk), str(response.data))

    def test_results_count_votes_without_repairing_legacy_stored_counter(self):
        option = self.options[self.public.pk][0]
        cast_vote(self.other, self.public.pk, option.pk)
        option.votes_count = 99
        option.save(update_fields=["votes_count"])
        before = self.snapshot()
        response = self.client.get(self.results(self.public))
        self.assertEqual(response.status_code, 200)
        row = next(
            item
            for item in response.data["options"]
            if item["id"] == str(option.pk)
        )
        self.assertEqual(row["total_votes"], 1)
        self.assertEqual(row["votes_count"], 1)
        self.assertEqual(self.snapshot(), before)
