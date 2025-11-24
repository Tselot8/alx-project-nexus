import pytest
from django.utils import timezone
from accounts.models import User
from polls.models import Category, Poll, Option, Vote
from polls.views import cast_vote
from django.test import TestCase

pytestmark = pytest.mark.django_db

class TestVoteService(TestCase):
    def test_user_can_vote_once(self):
        user = User.objects.create_user(email="a@a.com", username="a", password="pass")
        cat = Category.objects.create(name="General")
        poll = Poll.objects.create(question="Food?", category=cat, created_by=user)
        opt1 = Option.objects.create(poll=poll, option_text="Pizza")

        vote, count = cast_vote(user, poll.id, opt1.id)

        assert Vote.objects.count() == 1
        assert count == 1
        assert vote.option == opt1


    def test_user_can_change_vote(self):
        user = User.objects.create_user(email="a@a.com", username="a", password="pass")
        cat = Category.objects.create(name="General")
        poll = Poll.objects.create(question="Food?", category=cat, created_by=user)
        opt1 = Option.objects.create(poll=poll, option_text="Pizza")
        opt2 = Option.objects.create(poll=poll, option_text="Burger")

        # Initial vote
        cast_vote(user, poll.id, opt1.id)

        # Change vote
        vote, count = cast_vote(user, poll.id, opt2.id)

        opt1.refresh_from_db()
        opt2.refresh_from_db()

        assert Vote.objects.count() == 1
        assert vote.option == opt2
        assert opt1.votes_count == 0
        assert opt2.votes_count == 1


    def test_vote_same_option_no_change(self):
        user = User.objects.create_user(email="a@a.com", username="a", password="pass")
        cat = Category.objects.create(name="General")
        poll = Poll.objects.create(question="Food?", category=cat, created_by=user)
        opt1 = Option.objects.create(poll=poll, option_text="Pizza")

        cast_vote(user, poll.id, opt1.id)
        vote, count = cast_vote(user, poll.id, opt1.id)

        assert Vote.objects.count() == 1
        assert count == 1  # should remain the same

    def test_cannot_vote_on_expired_poll(self):
        user = User.objects.create_user(email="c@c.com", username="c", password="pass")
        cat = Category.objects.create(name="General")
        poll = Poll.objects.create(
            question="Old poll?",
            category=cat,
            created_by=user,
            expires_at=timezone.now() - timezone.timedelta(days=1)
        )
        opt = Option.objects.create(poll=poll, option_text="Option1")

        import pytest
        with pytest.raises(ValueError):
            cast_vote(user, poll.id, opt.id)
