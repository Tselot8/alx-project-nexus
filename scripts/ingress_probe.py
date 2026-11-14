"""Temporary opt-in WSGI probe; never imports Django or uses credentials/DBs.

Run with the existing Gunicorn config only during ingress verification. Switch
back to the normal application command before adding runtime secrets.
"""

import json
import os


def application(environ, start_response):
    method = environ.get("REQUEST_METHOD", "")
    path = environ.get("PATH_INFO", "")
    if os.getenv("NEXUS_INGRESS_PROBE_ENABLED") != "true":
        status, data = "503 Service Unavailable", {"status": "disabled"}
    elif method not in {"GET", "HEAD"}:
        status, data = "405 Method Not Allowed", {
            "status": "method_not_allowed"
        }
    elif path == "/health/live/":
        status, data = "200 OK", {"status": "ok", "mode": "ingress_probe"}
    elif path == "/probe/":
        proto = environ.get("HTTP_X_FORWARDED_PROTO")
        status, data = "200 OK", {
            "mode": "ingress_probe",
            "forwarded_proto_https": proto == "https",
            "forwarded_proto_http": proto == "http",
            "forwarded_proto_unexpected": proto not in {"http", "https"},
        }
    else:
        status, data = "404 Not Found", {"status": "not_found"}
    body = json.dumps(data, separators=(",", ":")).encode()
    headers = [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "private, no-store"),
        ("Referrer-Policy", "no-referrer"),
        ("X-Content-Type-Options", "nosniff"),
        ("X-Frame-Options", "DENY"),
        (
            "Content-Security-Policy",
            "default-src 'none'; frame-ancestors 'none'",
        ),
    ]
    if status.startswith("405"):
        headers.append(("Allow", "GET, HEAD"))
    start_response(status, headers)
    return [] if method == "HEAD" else [body]
