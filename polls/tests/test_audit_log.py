from django.test import TestCase
from accounts.models import User
from polls.models import Poll, Category, AuditLog
from rest_framework.test import APIClient
from django.test import TestCase

class AuditLogTest(TestCase):
    def test_poll_creation_logs_action(self):
        user = User.objects.create_user(email="a@test.com", username="a", password="pass")
        cat = Category.objects.create(name="General")
        client = APIClient()
        client.force_authenticate(user)
        
        resp = client.post("/api/polls/", {
            "question": "Test poll?",
            "category": str(cat.id),
            "options": [{"option_text": "Yes"}, {"option_text": "No"}]
        }, format="json")
        
        self.assertEqual(resp.status_code, 201)
        
        # Check AuditLog
        log = AuditLog.objects.last()
        self.assertEqual(log.action, "Created poll")
        self.assertEqual(log.user, user)
        self.assertEqual(log.target_type, "Poll")
        self.assertEqual(str(log.target_id), resp.data["id"])
