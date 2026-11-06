"""Real HTTP through Vite's proxy, with no mocked application responses."""

import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import http.cookiejar
import io
import json
import os
import secrets
import subprocess
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import (
    HTTPRedirectHandler,
    HTTPCookieProcessor,
    ProxyHandler,
    build_opener,
    Request,
)

import pytest
from django.conf import settings
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from django.utils import timezone

from polls.models import (
    AuditLog,
    Ballot,
    BallotSelection,
    Category,
    Option,
    Poll,
    PollShareToken,
    Vote,
)

PREFIX = "/api/v2/polls/"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Actor:
    def __init__(self, base):
        self.base = base
        self.cookies = http.cookiejar.CookieJar()
        self.opener = build_opener(
            ProxyHandler({}), NoRedirect(), HTTPCookieProcessor(self.cookies)
        )
        self.access = None
        self.csrf = None

    def __repr__(self):
        return "<disposable HTTP actor; credentials redacted>"

    def request(
        self,
        path,
        method="GET",
        data=None,
        *,
        expected=200,
        auth=True,
        csrf=True,
        share=None,
    ):
        assert path.startswith("/api/") and "://" not in path
        headers = {"Origin": self.base, "Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if auth and self.access:
            headers["Authorization"] = "Bearer " + self.access
        if csrf and self.csrf and method != "GET":
            headers["X-CSRFToken"] = self.csrf
        if share:
            headers["X-Poll-Share"] = share
        request = Request(
            self.base + path,
            method=method,
            headers=headers,
            data=json.dumps(data).encode() if data is not None else None,
        )
        try:
            response = self.opener.open(request, timeout=15)
        except HTTPError as error:
            response = error
        status = response.code
        body = response.read()
        assert (
            status == expected
        ), f"{method} API request returned HTTP {status}; expected {expected}."
        if expected >= 300:
            assert b"traceback" not in body.lower()
        value = json.loads(body) if body else None
        return value, response.headers

    def bootstrap(self):
        data, _ = self.request("/api/v2/auth/csrf/", auth=False)
        self.csrf = data["csrf_token"]

    def register(self, name):
        self.bootstrap()
        self.password = "Nexus!" + secrets.token_urlsafe(40)
        self.email = name + "@example.invalid"
        data, headers = self.request(
            "/api/v2/auth/register/",
            "POST",
            {"username": name, "email": self.email, "password": self.password},
            expected=201,
            auth=False,
        )
        assert set(data) == {"user", "access", "expires_in", "csrf_token"}
        assert "refresh" not in data
        self.access, self.csrf = data["access"], data["csrf_token"]
        self.user = data["user"]
        assert "no-store" in headers["Cache-Control"]
        return self

    def refresh(self, expected=200):
        data, headers = self.request(
            "/api/v2/auth/refresh/",
            "POST",
            {},
            auth=False,
            expected=expected,
        )
        if expected == 200:
            assert set(data) == {"access", "expires_in"}
            self.access = data["access"]
        return data, headers

    def cookie(self, name):
        return next(cookie for cookie in self.cookies if cookie.name == name)


def actors(base):
    return (
        Actor(base).register("creator"),
        Actor(base).register("voter"),
        Actor(base),
    )


def draft(owner, **fields):
    data, _ = owner.request(PREFIX, "POST", fields, expected=201)
    assert data["status"] == "draft"
    return data


def publish(owner, poll):
    data, _ = owner.request(PREFIX + poll["id"] + "/publish/", "POST", {})
    assert data["status"] == "published"
    return data


def action(owner, poll, operation, data=None, expected=200):
    return owner.request(
        PREFIX + poll["id"] + "/" + operation + "/",
        "POST",
        data or {},
        expected=expected,
    )[0]


def test_live_atomic_voting_discovery_and_lifecycle(full_stack):
    base, _ = full_stack
    owner, voter, guest = actors(base)
    category = Category.objects.create(name="Live integration")
    poll = draft(
        owner,
        question="",
        category=str(category.pk),
        voting_mode="multiple",
        min_selections=2,
        max_selections=2,
        results_visibility="after_voting",
    )
    url = PREFIX + poll["id"] + "/"
    owner.request(
        url,
        "PATCH",
        {
            "question": "Integration choices",
            "description": "Searchable live verification",
        },
    )
    options = []
    for label in ("Morning", "Afternoon", "Evening"):
        value, _ = owner.request(
            url + "options/", "POST", {"option_text": label}, expected=201
        )
        options.append(value)
    owner.request(
        url + "options/" + options[2]["id"] + "/",
        "PATCH",
        {"option_text": "Late evening"},
    )
    owner.request(url + "publish/", "POST", {}, expected=200)
    unrelated = publish(
        owner,
        draft(
            owner,
            question="Another public question",
            options=[{"option_text": "A"}, {"option_text": "B"}],
        ),
    )
    for filters in ({"q": "Searchable"}, {"category": str(category.pk)}):
        filtered, _ = guest.request(PREFIX + "?" + urlencode(filters))
        assert filtered["count"] == 1
        assert filtered["results"][0]["id"] == poll["id"]
    first_page, _ = guest.request(PREFIX + "?sort=oldest&page_size=1")
    assert first_page["count"] == 2 and first_page["next"] is not None
    second_page, _ = guest.request(PREFIX + "?sort=oldest&page_size=1&page=2")
    assert second_page["results"][0]["id"] == unrelated["id"]
    closed_list, _ = guest.request(PREFIX + "?status=closed")
    assert closed_list["count"] == 0
    query = urlencode(
        {
            "q": "Searchable",
            "category": str(category.pk),
            "sort": "oldest",
            "status": "published",
            "page_size": 1,
        }
    )
    listing, _ = guest.request(PREFIX + "?" + query)
    assert listing["count"] == 1
    assert listing["results"][0]["id"] == poll["id"]
    public, _ = guest.request(url)
    assert all(
        set(option) == {"id", "option_text"} for option in public["options"]
    )
    guest.request(url + "results/", expected=403)
    voter.request(url + "results/", expected=403)
    voter.request(url, "PATCH", {"description": "Forbidden"}, expected=403)
    before = (
        Ballot.objects.count(),
        BallotSelection.objects.count(),
        AuditLog.objects.count(),
    )
    voter.request(url + "ballots/", "POST", {"option_ids": []}, expected=400)
    assert before == (
        Ballot.objects.count(),
        BallotSelection.objects.count(),
        AuditLog.objects.count(),
    )
    first_ids = [row["id"] for row in options[:2]]
    receipt, _ = voter.request(
        url + "ballots/", "POST", {"option_ids": first_ids}
    )
    first_time = receipt["submitted_at"]
    voter.request(url + "ballots/", "POST", {"option_ids": first_ids})
    voter.request(
        url + "ballots/",
        "POST",
        {"option_ids": [options[0]["id"]]},
        expected=400,
    )
    replacement = [row["id"] for row in options[1:]]
    updated, _ = voter.request(
        url + "ballots/", "POST", {"option_ids": replacement}
    )
    assert updated["submitted_at"] == first_time
    saved, _ = voter.request(url + "ballots/")
    assert set(saved["option_ids"]) == set(replacement)
    assert Ballot.objects.count() == 1
    assert BallotSelection.objects.count() == 2
    assert Vote.objects.count() == 0
    results, _ = voter.request(url + "results/")
    assert results["total_participants"] == 1
    assert results["total_selections"] == 2
    assert sum(row["count"] for row in results["options"]) == 2
    assert "voters" not in results
    owner.request(url, "PATCH", {"question": "Locked"}, expected=400)
    voter.request(
        "/api/polls/" + poll["id"] + "/vote/" + options[0]["id"] + "/",
        "POST",
        {},
        expected=400,
    )
    action(owner, poll, "close")
    voter.request(
        url + "ballots/", "POST", {"option_ids": replacement}, expected=400
    )
    guest.request(url + "results/", expected=403)
    voter.request(url + "results/")
    action(owner, poll, "reopen", expected=400)
    action(owner, poll, "reopen", {"expires_at": None})
    action(owner, poll, "archive")
    owner.request(url, "PATCH", {"description": "Archived"}, expected=400)
    owner.request(url, "DELETE", expected=400)
    assert Poll.objects.get(pk=poll["id"]).status == "archived"


def test_live_legacy_bridge_and_after_closing_results(full_stack):
    base, _ = full_stack
    owner, voter, guest = actors(base)
    poll = publish(
        owner,
        draft(
            owner,
            question="Legacy bridge",
            results_visibility="after_closing",
            options=[{"option_text": "One"}, {"option_text": "Two"}],
        ),
    )
    url = PREFIX + poll["id"] + "/"
    first, second = poll["options"]
    legacy = "/api/polls/" + poll["id"] + "/vote/" + first["id"] + "/"
    voter.request(legacy, "POST", {})
    voter.request(legacy, "POST", {})
    assert Ballot.objects.count() == 1
    assert BallotSelection.objects.count() == 1
    assert not Vote.objects.exists()
    guest.request(url + "results/", expected=403)
    guest.request("/api/polls/" + poll["id"] + "/results/", expected=403)
    voter.request(url + "ballots/", "POST", {"option_ids": [second["id"]]})
    action(owner, poll, "close")
    results, _ = guest.request(url + "results/")
    assert results["total_participants"] == results["total_selections"] == 1
    action(owner, poll, "reopen", {"expires_at": None})
    guest.request(url + "results/", expected=403)
    Poll.objects.filter(pk=poll["id"]).update(expires_at=timezone.now())
    voter.request(
        url + "ballots/", "POST", {"option_ids": [first["id"]]}, expected=400
    )
    guest.request(url + "results/")
    action(owner, poll, "close")
    owner.request(
        url,
        "PATCH",
        {
            "expires_at": (timezone.now() + timedelta(days=1)).isoformat(),
        },
    )
    assert Poll.objects.get(pk=poll["id"]).status == "closed"


def test_live_private_sharing_is_scoped_and_read_only(full_stack):
    base, _ = full_stack
    owner, voter, guest = actors(base)
    poll = publish(
        owner,
        draft(
            owner,
            question="Private integration",
            visibility="private",
            results_visibility="after_voting",
            options=[{"option_text": "Yes"}, {"option_text": "No"}],
        ),
    )
    url = PREFIX + poll["id"] + "/"
    issued, _ = owner.request(url + "share/", "POST", {}, expected=201)
    token = issued["token"]
    assert len(token) == 43
    assert PollShareToken.objects.get(poll_id=poll["id"]).token_digest != token
    status, _ = owner.request(url + "share/")
    assert "token" not in status
    resolved, _ = guest.request(
        "/api/v2/shares/resolve/", "POST", {"token": token}
    )
    assert resolved["poll"]["id"] == poll["id"]
    guest.request(url, expected=404)
    guest.request(url + "?token=not-a-share-credential", expected=404)
    _, headers = guest.request(url, share=token)
    assert "no-store" in headers["Cache-Control"]
    guest.request(url + "results/", share=token, expected=403)
    voter.request(
        url + "ballots/",
        "POST",
        {
            "option_ids": [poll["options"][0]["id"]],
        },
        share=token,
        expected=404,
    )
    guest.request(url + "ballots/", "POST", {}, share=token, expected=401)
    listing, _ = owner.request(PREFIX)
    assert listing["count"] == 0
    mine, _ = owner.request(PREFIX + "mine/")
    assert mine["count"] == 1
    other = publish(
        owner,
        draft(
            owner,
            question="Another private",
            visibility="private",
            options=[{"option_text": "A"}, {"option_text": "B"}],
        ),
    )
    guest.request(PREFIX + other["id"] + "/", share=token, expected=404)
    renewed, _ = owner.request(
        url + "share/regenerate/", "POST", {}, expected=201
    )
    assert renewed["generation"] > issued["generation"]
    guest.request(url, share=token, expected=404)
    guest.request(url, share=renewed["token"])
    guest.request(
        "/api/v2/shares/resolve/", "POST", {"token": token}, expected=404
    )
    owner.request(url + "share/", "DELETE", expected=204)
    guest.request(url, share=renewed["token"], expected=404)


def test_live_csrf_rotation_profile_and_revocation(full_stack):
    base, _ = full_stack
    owner = Actor(base).register("account")
    cookie = owner.cookie("nexus_v2_refresh_token")
    assert cookie.path == "/api/v2/auth/"
    assert not cookie.secure  # Explicitly isolated HTTP settings only.
    assert cookie.has_nonstandard_attr("HttpOnly")
    assert cookie.get_nonstandard_attr("SameSite") == "Lax"
    owner.request(
        "/api/v2/auth/refresh/",
        "POST",
        {},
        auth=False,
        csrf=False,
        expected=403,
    )
    stale = Actor(base)
    for stored_cookie in owner.cookies:
        stale.cookies.set_cookie(copy.copy(stored_cookie))
    stale.opener = build_opener(
        ProxyHandler({}), NoRedirect(), HTTPCookieProcessor(stale.cookies)
    )
    stale.csrf = owner.csrf
    old_access = owner.access
    owner.refresh()
    assert cookie.value != owner.cookie("nexus_v2_refresh_token").value
    stale.refresh(expected=401)
    me, _ = owner.request("/api/v2/auth/me/")
    assert me["user"]["id"] == owner.user["id"]
    owner.request(
        "/api/v2/auth/me/",
        "PATCH",
        {"profile": {"bio": "Live profile", "location": "Local only"}},
    )
    owner.request(
        "/api/v2/auth/me/", "PATCH", {"is_staff": True}, expected=400
    )
    new_password = "Changed!" + secrets.token_urlsafe(40)
    owner.request(
        "/api/v2/auth/password/change/",
        "POST",
        {
            "current_password": owner.password,
            "new_password": new_password,
        },
        expected=204,
    )
    owner.request("/api/v2/auth/me/", expected=401)
    stale.access = old_access
    stale.request("/api/v2/auth/me/", expected=401)
    owner.refresh(expected=401)
    owner.bootstrap()
    data, _ = owner.request(
        "/api/v2/auth/login/",
        "POST",
        {
            "email": owner.email,
            "password": new_password,
        },
        auth=False,
    )
    owner.access, owner.csrf = data["access"], data["csrf_token"]
    owner.request("/api/v2/auth/logout/", "POST", {}, csrf=False, expected=403)
    owner.request("/api/v2/auth/logout/", "POST", {}, expected=204)
    owner.refresh(expected=401)
    owner.request(
        "/api/v2/auth/password/reset/",
        "POST",
        {"email": owner.email},
        auth=False,
        expected=503,
    )
    assert not getattr(mail, "outbox", [])


def test_live_historical_reconciliation_preserves_evidence(full_stack):
    base, _ = full_stack
    owner, voter, guest = actors(base)
    poll = Poll.objects.create(
        question="Historical fixture", created_by_id=owner.user["id"]
    )
    first = Option.objects.create(poll=poll, option_text="A", votes_count=99)
    second = Option.objects.create(poll=poll, option_text="B", votes_count=99)
    old = Vote.objects.create(
        poll=poll, option=first, user_id=voter.user["id"]
    )
    source = list(Vote.objects.values())
    url = PREFIX + str(poll.pk) + "/"
    before, _ = guest.request(url + "results/")
    assert before["total_participants"] == before["total_selections"] == 1
    output = io.StringIO()
    with pytest.raises(CommandError):
        call_command("backfill_ballots", reconcile=True, stdout=output)
    report = json.loads(output.getvalue())
    assert report["quarantined"] == {"unconverted_history": 1}
    output = io.StringIO()
    call_command("backfill_ballots", dry_run=True, stdout=output)
    assert json.loads(output.getvalue())["counts"] == {"would_convert": 1}
    assert not Ballot.objects.exists()
    for _ in range(2):
        call_command(
            "backfill_ballots",
            apply=True,
            confirm_frozen_writers=True,
            stdout=io.StringIO(),
        )
    assert list(Vote.objects.values()) == source
    imported = Ballot.objects.get()
    assert (
        imported.source == "legacy" and imported.submitted_at == old.voted_at
    )
    with override_settings(NEXUS_BALLOT_AUTHORITY="ballots"):
        data, _ = guest.request(url + "results/")
        assert data["authority"] == "ballots"
        assert data["total_participants"] == data["total_selections"] == 1
    voter.request(url + "ballots/", "POST", {"option_ids": [str(second.pk)]})
    assert list(Vote.objects.values()) == source
    after, _ = guest.request(url + "results/")
    assert after["total_participants"] == after["total_selections"] == 1
    assert (
        next(row for row in after["options"] if row["id"] == str(second.pk))[
            "count"
        ]
        == 1
    )
    # A legal-sized partial migration with no receipt must fail closed.
    BallotSelection.objects.filter(ballot=imported).delete()
    guest.request(url + "results/", expected=503)
    assert list(Vote.objects.values()) == source
    assert settings.NEXUS_BALLOT_AUTHORITY == "bridge"


def test_real_browser_workflows(full_stack):
    if os.getenv("NEXUS_INTEGRATION_HTTP_ONLY") == "1":
        pytest.skip("Browser verification explicitly disabled by --http-only.")
    _, env = full_stack
    Category.objects.create(name="Browser topics")
    result = subprocess.run(
        [
            "node",
            "node_modules/@playwright/test/cli.js",
            "test",
            "--project",
            "desktop-chrome",
            "--project",
            "mobile-chrome",
        ],
        cwd=env["NEXUS_INTEGRATION_FRONTEND_DIR"],
        env=env,
        check=False,
    )
    assert (
        result.returncode == 0
    ), "Real browser workflows failed; see the credential-safe browser report."


def test_live_concurrent_complete_replacements_never_mix_sets(full_stack):
    base, _ = full_stack
    owner, voter, guest = actors(base)
    poll = publish(
        owner,
        draft(
            owner,
            question="Concurrent HTTP ballots",
            voting_mode="multiple",
            min_selections=2,
            max_selections=2,
            options=[
                {"option_text": "A"},
                {"option_text": "B"},
                {"option_text": "C"},
            ],
        ),
    )
    url = PREFIX + poll["id"] + "/"
    ids = [option["id"] for option in poll["options"]]
    sets = [ids[:2], ids[1:], ids[:2], ids[1:]]

    def replace(selected):
        client = Actor(base)
        client.access = voter.access
        client.request(url + "ballots/", "POST", {"option_ids": selected})
        totals, _ = client.request(url + "results/")
        assert totals["total_participants"] == 1
        assert totals["total_selections"] == 2
        assert sum(row["count"] for row in totals["options"]) == 2

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(replace, sets))
    saved, _ = voter.request(url + "ballots/")
    assert set(saved["option_ids"]) in (set(ids[:2]), set(ids[1:]))
    assert Ballot.objects.count() == 1
    assert BallotSelection.objects.count() == 2
    assert not Vote.objects.exists()
