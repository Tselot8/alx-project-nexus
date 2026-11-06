"""HTTP parser and response-header boundaries exercised through middleware."""

from django.test import TestCase

from .test_v2_discovery import EFixtures


class HttpBoundaryTests(EFixtures, TestCase):
    def test_untrusted_origin_gets_no_credential_access_or_embed_permission(
        self,
    ):
        for path in (self.detail(self.public), self.detail(self.private)):
            response = self.guest.get(
                path, HTTP_ORIGIN="https://untrusted.example.invalid"
            )
            self.assertIn(response.status_code, (200, 404))
            self.assertNotIn("Access-Control-Allow-Origin", response)
            self.assertNotIn("Access-Control-Allow-Credentials", response)
            self.assertEqual(response["X-Content-Type-Options"], "nosniff")
            self.assertEqual(response["X-Frame-Options"], "DENY")
            self.assertEqual(response["Referrer-Policy"], "no-referrer")
            self.assertIn("no-store", response["Cache-Control"])

    def test_malformed_json_cannot_partially_mutate_poll_or_ballot(self):
        client = self.auth()
        for method, path in (
            ("post", "/api/v2/polls/"),
            ("patch", self.detail(self.public)),
            ("post", self.action(self.public, "ballots")),
        ):
            with self.subTest(method=method, path=path):
                before = self.state()
                response = getattr(client, method)(
                    path, b'{"question":', content_type="application/json"
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(self.state(), before)
