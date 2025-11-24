import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from accounts.models import User
from polls.models import Category, Poll, Option, Vote
from polls.views import cast_vote
from django.test import TestCase

pytestmark = pytest.mark.django_db


class TestResultsApi(TestCase):
    def make_client(self):
        return APIClient()

    def create_user(self, email="u@test.com"):
        return User.objects.create_user(
            email=email,
            username=email.split("@")[0],
            password="pass1234"
        )

    def create_poll_with_options(self, user, option_texts=("A", "B", "C")):
        cat = Category.objects.create(name="test-cat")
        poll = Poll.objects.create(question="Q?", created_by=user, category=cat)
        opts = [Option.objects.create(poll=poll, option_text=txt) for txt in option_texts]
        return poll, opts

    def test_results_empty_poll(self):
        user = self.create_user("a@test.com")
        poll, opts = self.create_poll_with_options(user, ("yes", "no"))
        client = self.make_client()
        client.force_authenticate(user)
        url = reverse('poll-results', args=[poll.id])
        resp = client.get(url)
        assert resp.status_code == 200
        data = resp.json()
        assert data["poll_id"] == str(poll.id)
        assert len(data["options"]) == 2
        for o in data["options"]:
            assert o["total_votes"] == 0

    def test_results_reflects_votes_and_vote_change(self):
        user = self.create_user("b@test.com")
        other = self.create_user("c@test.com")
        poll, opts = self.create_poll_with_options(user, ("yes", "no"))

        # user votes yes
        cast_vote(user, poll.id, opts[0].id)
        # other votes no
        cast_vote(other, poll.id, opts[1].id)

        client = self.make_client()
        client.force_authenticate(user)
        url = reverse('poll-results', args=[poll.id])
        resp = client.get(url)
        assert resp.status_code == 200
        data = resp.json()

        # two total votes
        total = sum(item["total_votes"] for item in data["options"])
        assert total == 2

        # user changes vote to 'no'
        cast_vote(user, poll.id, opts[1].id)

        resp2 = client.get(url)
        data2 = resp2.json()
        total2 = sum(item["total_votes"] for item in data2["options"])
        assert total2 == 2  # stays 2

        mapping = {o["option_text"]: o["total_votes"] for o in data2["options"]}
        assert mapping["yes"] == 0
        assert mapping["no"] == 2

    def test_results_cache_invalidation(self):
        user = self.create_user("cache@test.com")
        poll, opts = self.create_poll_with_options(user, ("one", "two"))
        client = self.make_client()
        client.force_authenticate(user)
        url = reverse('poll-results', args=[poll.id])

        # warm cache
        resp1 = client.get(url)
        self.assertEqual(resp1.status_code, 200)

        # cast a vote (this should invalidate cache)
        cast_vote(user, poll.id, opts[0].id)

        # After vote, results should reflect change (not stale)
        resp2 = client.get(url)
        data = resp2.json()
        self.assertEqual(sum(o["total_votes"] for o in data["options"]), 1)