import json
from rest_framework.test import APITestCase
from django.urls import reverse
from accounts.models import User
from polls.models import Category, Poll, Option

class PollsApiTest(APITestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="admin@test.com",
            username="admin",
            password="pass1234"
        )
        self.client.force_authenticate(self.user)

        self.category = Category.objects.create(name="General")

    def test_create_poll_with_options(self):
        url = reverse('poll-list-create')
        payload = {
            "question": "What is the best fruit?",
            "description": "Test question",
            "category": str(self.category.id),
            "options": [
                {"option_text": "Apple"},
                {"option_text": "Banana"},
            ]
        }

        response = self.client.post(url, payload, format='json')
        self.assertEqual(response.status_code, 201)
        poll_id = response.data["id"]

        poll = Poll.objects.get(id=poll_id)
        self.assertEqual(poll.options.count(), 2)

    def test_get_poll_detail(self):
        poll = Poll.objects.create(
            question="Best color?",
            created_by=self.user,
            category=self.category
        )
        Option.objects.create(poll=poll, option_text="Red")
        Option.objects.create(poll=poll, option_text="Blue")

        url = reverse('poll-detail', args=[poll.id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["options"]), 2)

    def test_update_poll(self):
        poll = Poll.objects.create(
            question="Old question?",
            created_by=self.user,
            category=self.category
        )

        url = reverse('poll-detail', args=[poll.id])
        response = self.client.patch(url, {"question": "Updated"}, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["question"], "Updated")

    def test_delete_poll(self):
        poll = Poll.objects.create(
            question="Delete me?",
            created_by=self.user,
            category=self.category
        )
        url = reverse('poll-detail', args=[poll.id])
        response = self.client.delete(url)

        self.assertEqual(response.status_code, 204)

    def test_add_option_to_poll(self):
        poll = Poll.objects.create(
            question="Favorite drink?",
            created_by=self.user,
            category=self.category
        )

        url = reverse('option-create', args=[poll.id])
        response = self.client.post(url, {"option_text": "Coffee"}, format='json')

        self.assertEqual(response.status_code, 201)
        self.assertEqual(poll.options.count(), 1)
