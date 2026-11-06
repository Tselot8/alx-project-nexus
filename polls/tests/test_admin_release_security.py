"""Admin users must not bypass poll invariants or rewrite audit evidence."""

from django.contrib import admin
from django.test import RequestFactory, TestCase
from django.urls import reverse

from accounts.models import User
from polls.models import AuditLog, Category, Option, Poll, Vote
from .test_v2_discovery import EFixtures


class AdminReleaseSecurityTests(EFixtures, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.staff)
        self.audit = AuditLog.objects.create(
            user=self.owner,
            action="Fixture audit event",
            target_type="Poll",
            target_id=self.public.pk,
        )
        self.records = [
            (Poll, self.public),
            (Option, self.option(self.public)),
            (AuditLog, self.audit),
        ]

    def endpoint(self, model, action, obj=None):
        return reverse(
            "admin:polls_" + model._meta.model_name + "_" + action,
            args=[obj.pk] if obj else [],
        )

    def test_superusers_can_read_but_have_no_mutation_permissions(self):
        request = RequestFactory().get("/admin/")
        request.user = self.staff
        for model, obj in self.records:
            with self.subTest(model=model.__name__):
                model_admin = admin.site._registry[model]
                self.assertTrue(model_admin.has_view_permission(request, obj))
                self.assertFalse(model_admin.has_add_permission(request))
                self.assertFalse(
                    model_admin.has_change_permission(request, obj)
                )
                self.assertFalse(
                    model_admin.has_delete_permission(request, obj)
                )
                self.assertEqual(model_admin.get_actions(request), {})
                self.assertEqual(
                    self.client.get(
                        self.endpoint(model, "changelist")
                    ).status_code,
                    200,
                )
                response = self.client.get(self.endpoint(model, "change", obj))
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, 'name="_save"')
                self.assertNotContains(response, 'name="_selected_action"')

    def test_direct_admin_mutations_leave_state_unchanged(
        self,
    ):
        before = self.state()
        for model, obj in self.records:
            for action, target in (
                ("add", None),
                ("change", obj),
                ("delete", obj),
            ):
                with self.subTest(model=model.__name__, action=action):
                    path = self.endpoint(model, action, target)
                    response = self.client.post(
                        path,
                        {
                            "question": "Injected",
                            "option_text": "Injected",
                            "action": "Injected",
                            "post": "yes",
                        },
                    )
                    self.assertEqual(response.status_code, 403)
                    self.assertEqual(before, self.state())

    def test_bulk_delete_action_cannot_mutate_any_read_only_record(self):
        before = self.state()
        for model, obj in self.records:
            with self.subTest(model=model.__name__):
                response = self.client.post(
                    self.endpoint(model, "changelist"),
                    {
                        "action": "delete_selected",
                        "_selected_action": [str(obj.pk)],
                        "index": "0",
                        "post": "yes",
                    },
                )
                self.assertIn(response.status_code, (200, 302, 403))
                self.assertEqual(before, self.state())

    def test_poll_inline_cannot_change_options_or_an_archived_poll(self):
        request = RequestFactory().get("/admin/")
        request.user = self.staff
        poll_admin = admin.site._registry[Poll]
        self.assertEqual(
            poll_admin.get_inline_instances(request, self.public), []
        )
        before = self.state()
        response = self.client.post(
            self.endpoint(Poll, "change", self.archived),
            {
                "question": "Changed archived",
                "options-TOTAL_FORMS": "1",
                "options-INITIAL_FORMS": "0",
                "options-0-option_text": "Injected option",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(before, self.state())

    def test_account_category_management_and_historical_vote_protection_remain(
        self,
    ):
        request = RequestFactory().get("/admin/")
        request.user = self.staff
        for model in (User, Category):
            self.assertTrue(
                admin.site._registry[model].has_change_permission(request)
            )
            self.assertTrue(
                admin.site._registry[model].has_add_permission(request)
            )
        historical = admin.site._registry[Vote]
        self.assertFalse(historical.has_add_permission(request))
        self.assertFalse(historical.has_change_permission(request))
        self.assertFalse(historical.has_delete_permission(request))
