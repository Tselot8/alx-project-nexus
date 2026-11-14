"""Credential-free ingress inspection must never expose an application API."""

import json
import os
import unittest
from unittest.mock import patch

from scripts.ingress_probe import application


class IngressProbeTests(unittest.TestCase):
    def request(self, path="/probe/", method="GET", **extra):
        result = {}

        def start(status, headers):
            result.update(status=status, headers=dict(headers))

        body = b"".join(
            application(
                {"PATH_INFO": path, "REQUEST_METHOD": method, **extra}, start
            )
        )
        return result, body

    def test_explicit_opt_in_is_required(self):
        for value in (None, "false", "TRUE", "1"):
            with self.subTest(value=value), patch.dict(
                os.environ, {}, clear=True
            ):
                if value is not None:
                    os.environ["NEXUS_INGRESS_PROBE_ENABLED"] = value
                result, body = self.request()
                self.assertTrue(result["status"].startswith("503"))
                self.assertEqual(json.loads(body), {"status": "disabled"})

    @patch.dict(os.environ, {"NEXUS_INGRESS_PROBE_ENABLED": "true"})
    def test_exact_protocol_observation_without_trusting_or_reflecting_inputs(
        self,
    ):
        for value in (
            "https",
            "http",
            "http, https",
            "https, http",
            "HTTPS",
            "",
            None,
        ):
            with self.subTest(value=value):
                result, body = self.request(
                    HTTP_X_FORWARDED_PROTO=value,
                    HTTP_HOST="synthetic-private-host",
                    HTTP_AUTHORIZATION="synthetic-private-authorization",
                    HTTP_COOKIE="synthetic-private-cookie",
                    HTTP_X_POLL_SHARE="synthetic-private-share",
                )
                data = json.loads(body)
                self.assertTrue(result["status"].startswith("200"))
                self.assertEqual(
                    data,
                    {
                        "mode": "ingress_probe",
                        "forwarded_proto_https": value == "https",
                        "forwarded_proto_http": value == "http",
                        "forwarded_proto_unexpected": value
                        not in {"http", "https"},
                    },
                )
                self.assertNotIn(b"synthetic-private", body)
                self.assertNotIn("Set-Cookie", result["headers"])
                self.assertEqual(
                    result["headers"]["Cache-Control"], "private, no-store"
                )

    @patch.dict(os.environ, {"NEXUS_INGRESS_PROBE_ENABLED": "true"})
    def test_liveness_and_head_are_generic_and_read_only(self):
        result, body = self.request("/health/live/")
        self.assertEqual(
            json.loads(body), {"status": "ok", "mode": "ingress_probe"}
        )
        result, body = self.request("/health/live/", method="HEAD")
        self.assertTrue(result["status"].startswith("200"))
        self.assertEqual(body, b"")

    @patch.dict(os.environ, {"NEXUS_INGRESS_PROBE_ENABLED": "true"})
    def test_application_routes_and_mutations_are_not_served(self):
        for path in (
            "/",
            "/health/ready/",
            "/api/v2/polls/",
            "/api/v2/auth/register/",
        ):
            with self.subTest(path=path):
                self.assertTrue(
                    self.request(path)[0]["status"].startswith("404")
                )
        for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
            with self.subTest(method=method):
                result, _ = self.request(method=method)
                self.assertTrue(result["status"].startswith("405"))
                self.assertEqual(result["headers"]["Allow"], "GET, HEAD")
