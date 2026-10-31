"""Read capabilities, revocation and results privacy."""

import json
import secrets
from datetime import timedelta

from django.core.cache import cache
from django.http import HttpRequest
from django.test import TestCase
from django.utils import timezone
from django.views.debug import get_exception_reporter_filter

from polls.models import Poll, PollShareToken
from polls.policy import share_digest
from .test_v2_discovery import BASE, EFixtures


class ShareTests(EFixtures, TestCase):
    def issue(self, poll=None):
        poll = poll or self.private
        response = self.auth().post(
            self.action(poll, "share"), {}, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        return response.data["token"]

    def test_tokens_are_256_bits_domain_separated_and_stored_digest_only(self):
        import base64
        import hashlib

        raw = self.issue()
        self.assertEqual(len(base64.urlsafe_b64decode(raw + "=")), 32)
        record = PollShareToken.objects.get(poll=self.private)
        self.assertEqual(len(record.token_digest), 64)
        self.assertTrue(record.token_digest == share_digest(raw))
        self.assertTrue(
            record.token_digest != hashlib.sha256(raw.encode()).hexdigest()
        )
        self.assertTrue(
            raw
            not in json.dumps(
                list(PollShareToken.objects.values()), default=str
            )
        )
        self.assertEqual(record.generation, 1)
        metadata = self.auth().get(self.action(self.private, "share"))
        self.assertEqual(
            set(metadata.data), {"poll_id", "active", "generation"}
        )
        self.assertTrue(raw not in json.dumps(metadata.data))
        self.assertEqual(metadata["Cache-Control"], "private, no-store")

    def test_resolution_and_scoped_headers_allow_only_one_poll_reads(self):
        raw = self.issue()
        response = self.guest.post(
            BASE + "shares/resolve/", {"token": raw}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["poll"]["id"], str(self.private.pk))
        self.assertTrue(raw not in json.dumps(response.json()))
        self.assertEqual(response["Cache-Control"], "private, no-store")
        for path in (
            self.detail(self.private),
            self.action(self.private, "options"),
            self.action(self.private, "options")
            + str(self.option(self.private).pk)
            + "/",
        ):
            result = self.guest.get(path, HTTP_X_POLL_SHARE=raw)
            self.assertEqual(result.status_code, 200)
            self.assertTrue(raw not in json.dumps(result.json()))
        second = Poll.objects.create(
            question="Another private",
            created_by=self.owner,
            is_public=False,
            configuration_locked=False,
        )
        self.assertEqual(
            self.guest.get(
                self.detail(second), HTTP_X_POLL_SHARE=raw
            ).status_code,
            404,
        )
        self.assertEqual(
            self.guest.get(
                self.legacy(self.private), HTTP_X_POLL_SHARE=raw
            ).status_code,
            404,
        )

    def test_share_credentials_grant_neither_writes_nor_voting(self):
        raw = self.issue()
        for client, expected in (
            (self.guest, 401),
            (self.auth(self.other), 404),
            (self.auth(self.staff), 404),
        ):
            for method, path, body in (
                ("patch", self.detail(self.private), {"description": "No"}),
                ("delete", self.detail(self.private), {}),
                ("post", self.vote_url(self.private), {}),
                ("post", self.action(self.private, "close"), {}),
                ("post", self.action(self.private, "share"), {}),
            ):
                self.rejected(
                    client, method, path, expected, body, HTTP_X_POLL_SHARE=raw
                )
        self.assert_no_ballots()

    def test_regeneration_and_revocation_invalidate_existing_headers_and_links(
        self,
    ):
        raw = self.issue()
        self.rejected(
            self.auth(), "post", self.action(self.private, "share"), 409
        )
        regenerated = self.auth().post(
            self.action(self.private, "share/regenerate"), {}, format="json"
        )
        self.assertEqual(regenerated.status_code, 201)
        current = regenerated.data["token"]
        self.assertTrue(current != raw)
        self.assertEqual(regenerated.data["generation"], 2)
        self.assertEqual(
            self.guest.get(
                self.detail(self.private), HTTP_X_POLL_SHARE=raw
            ).status_code,
            404,
        )
        self.assertEqual(
            self.guest.post(
                BASE + "shares/resolve/", {"token": raw}, format="json"
            ).status_code,
            404,
        )
        self.assertEqual(
            self.guest.get(
                self.detail(self.private), HTTP_X_POLL_SHARE=current
            ).status_code,
            200,
        )
        self.assertEqual(
            self.auth().delete(self.action(self.private, "share")).status_code,
            204,
        )
        self.assertEqual(
            self.guest.get(
                self.detail(self.private), HTTP_X_POLL_SHARE=current
            ).status_code,
            404,
        )
        record = PollShareToken.objects.get(poll=self.private)
        self.assertIsNone(record.token_digest)
        self.assertEqual(record.generation, 3)
        self.private.refresh_from_db()
        # Token generation is its own version, independent of poll content.
        self.assertEqual(self.private.version, 1)

    def test_query_parameters_and_wrong_methods_are_never_capabilities(self):
        raw = self.issue()
        for query in ("?token=" + raw, "?share=" + raw):
            self.assertEqual(
                self.guest.get(self.detail(self.private) + query).status_code,
                404,
            )
        self.assertEqual(
            self.guest.post(
                BASE + "shares/resolve/?token=" + raw, {}, format="json"
            ).status_code,
            400,
        )
        self.assertEqual(
            self.auth()
            .get(self.action(self.private, "share/regenerate"))
            .status_code,
            405,
        )

    def test_closed_archived_links_read_and_archived_revocation_is_still_safe(
        self,
    ):
        raw = self.issue()
        owner = self.auth()
        self.assertEqual(
            owner.post(
                self.action(self.private, "close"), {}, format="json"
            ).status_code,
            200,
        )
        self.assertEqual(
            self.guest.get(
                self.detail(self.private), HTTP_X_POLL_SHARE=raw
            ).status_code,
            200,
        )
        self.assertEqual(
            owner.post(
                self.action(self.private, "archive"), {}, format="json"
            ).status_code,
            200,
        )
        before = Poll.objects.values().get(pk=self.private.pk)
        for action in ("share", "share/regenerate"):
            self.rejected(
                owner, "post", self.action(self.private, action), 400
            )
        self.assertEqual(
            self.guest.get(
                self.detail(self.private), HTTP_X_POLL_SHARE=raw
            ).status_code,
            200,
        )
        self.assertEqual(
            owner.delete(self.action(self.private, "share")).status_code, 204
        )
        self.assertEqual(Poll.objects.values().get(pk=self.private.pk), before)
        self.assertEqual(
            self.guest.get(
                self.detail(self.private), HTTP_X_POLL_SHARE=raw
            ).status_code,
            404,
        )

    def test_drafts_and_public_polls_cannot_issue_share_links(self):
        for poll in (self.draft, self.public):
            self.rejected(self.auth(), "post", self.action(poll, "share"), 400)

    def test_visibility_changes_permanently_revoke_previous_credentials(
        self,
    ):
        raw = self.issue()
        owner = self.auth()
        for visibility in ("public", "private"):
            response = owner.patch(
                self.detail(self.private),
                {"visibility": visibility},
                format="json",
            )
            self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.guest.get(
                self.detail(self.private), HTTP_X_POLL_SHARE=raw
            ).status_code,
            404,
        )
        self.assertIsNone(
            PollShareToken.objects.get(poll=self.private).token_digest
        )

    def test_invalid_and_missing_tokens_do_not_reveal_hidden_poll_existence(
        self,
    ):
        response = self.guest.post(
            BASE + "shares/resolve/",
            {"token": secrets.token_urlsafe(32)},
            format="json",
        )
        self.assertEqual(response.status_code, 404)
        for raw in ("", "short", "a" * 44):
            response = self.guest.post(
                BASE + "shares/resolve/", {"token": raw}, format="json"
            )
            self.assertEqual(response.status_code, 400)

    def test_share_header_is_redacted_from_django_exception_metadata(self):
        raw = self.issue()
        request = HttpRequest()
        request.META["HTTP_X_POLL_SHARE"] = raw
        filtered = get_exception_reporter_filter(
            request
        ).get_safe_request_meta(request)
        self.assertTrue(raw not in str(filtered))


class ResultsPrivacyTests(EFixtures, TestCase):
    def set_policy(self, policy):
        Poll.objects.filter(pk=self.public.pk).update(
            results_visibility=policy
        )

    def test_after_voting_masks_nested_and_direct_option_counters(self):
        self.set_policy("after_voting")
        option = self.option(self.public)
        option.votes_count = 41
        option.save(update_fields=["votes_count"])
        response = self.guest.get(self.legacy(self.public))
        self.assertTrue(
            all(
                item["votes_count"] is None
                for item in response.data["options"]
            )
        )
        direct = self.guest.get(f"/api/polls/options/{option.pk}/")
        self.assertIsNone(direct.data["votes_count"])
        self.assertEqual(
            self.guest.get(self.legacy(self.public) + "results/").status_code,
            403,
        )
        html = self.guest.get(
            self.legacy(self.public), HTTP_ACCEPT="text/html"
        )
        self.assertEqual(html.status_code, 200)
        self.assertTrue(
            all(row["votes_count"] is None for row in html.data["options"])
        )
        creator = self.auth().get(self.legacy(self.public) + "results/")
        self.assertEqual(creator.status_code, 200)
        self.assertEqual(creator.data["total_votes"], 0)

    def test_after_voting_still_requires_participation_after_closure(self):
        self.set_policy("after_voting")
        voter = self.auth(self.other)
        self.assertEqual(
            voter.post(self.vote_url(self.public)).status_code, 200
        )
        self.assertEqual(
            self.auth()
            .post(self.action(self.public, "close"), {}, format="json")
            .status_code,
            200,
        )
        self.assertEqual(
            self.guest.get(self.legacy(self.public) + "results/").status_code,
            403,
        )
        result = voter.get(self.legacy(self.public) + "results/")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.data["total_votes"], 1)
        self.assertNotIn("user", str(result.data))

    def test_after_closing_masks_vote_response_and_relocks_on_reopen(self):
        self.set_policy("after_closing")
        prior_content_update = self.public.updated_at
        voter = self.auth(self.other)
        response = voter.post(self.vote_url(self.public))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["votes_count"])
        self.public.refresh_from_db()
        self.assertEqual(self.public.updated_at, prior_content_update)
        self.assertEqual(
            voter.get(self.legacy(self.public) + "results/").status_code, 403
        )
        owner = self.auth()
        self.assertEqual(
            owner.post(
                self.action(self.public, "close"), {}, format="json"
            ).status_code,
            200,
        )
        self.assertEqual(
            self.guest.get(self.legacy(self.public) + "results/").status_code,
            200,
        )
        self.assertEqual(
            owner.post(
                self.action(self.public, "reopen"),
                {"expires_at": None},
                format="json",
            ).status_code,
            200,
        )
        self.assertEqual(
            voter.get(self.legacy(self.public) + "results/").status_code, 403
        )
        option = self.option(self.public)
        self.assertIsNone(
            voter.get(f"/api/polls/options/{option.pk}/").data["votes_count"]
        )

    def test_expiration_and_archival_end_voting_for_after_closing_results(
        self,
    ):
        self.set_policy("after_closing")
        Poll.objects.filter(pk=self.public.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        self.assertEqual(
            self.guest.get(self.legacy(self.public) + "results/").status_code,
            200,
        )
        self.assertEqual(
            self.auth()
            .post(self.action(self.public, "archive"), {}, format="json")
            .status_code,
            200,
        )
        self.assertEqual(
            self.guest.get(self.legacy(self.public) + "results/").status_code,
            200,
        )

    def test_stale_cache_cannot_override_restrictions_and_v2_has_no_results(
        self,
    ):
        self.set_policy("after_closing")
        cache.set(
            "poll_results:" + str(self.public.pk), {"total_votes": 12345}
        )
        self.assertEqual(
            self.guest.get(self.legacy(self.public) + "results/").status_code,
            403,
        )
        self.assertEqual(
            self.guest.get(self.detail(self.public) + "results/").status_code,
            404,
        )
        for client in (self.guest, self.auth(self.other)):
            data = client.get(self.detail(self.public)).data
            self.assertNotIn("total_votes", data)
            self.assertTrue(
                all(
                    set(option) == {"id", "option_text"}
                    for option in data["options"]
                )
            )
        self.assert_no_ballots()
