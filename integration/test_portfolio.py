"""Portfolio activation is rehearsed only on the owned disposable stack."""

import pytest
from django.test import override_settings

from polls.models import AuditLog, Ballot, BallotSelection, Vote
from integration.test_workflows import Actor, PREFIX, draft, publish


@pytest.mark.parametrize("authority", ["bridge", "ballots"])
def test_recruiter_journey_and_activation_gates(full_stack, authority):
    base, _ = full_stack
    guest = Actor(base)
    guest.bootstrap()
    with override_settings(
        NEXUS_REGISTRATION_ENABLED=False,
        NEXUS_BALLOT_WRITES_ENABLED=False,
        NEXUS_BALLOT_AUTHORITY=authority,
        NEXUS_PASSWORD_RESET_ENABLED=False,
    ):
        for path in ("/api/v2/auth/register/", "/api/accounts/register/"):
            guest.request(path, "POST", {}, expected=503)

        # Approval is represented by a test-only override, not new defaults.
        with override_settings(NEXUS_REGISTRATION_ENABLED=True):
            owner = Actor(base).register("portfolio-creator")
            voter = Actor(base).register("portfolio-voter")

        # Exercise explicit login, not only registration's automatic session.
        owner.request("/api/v2/auth/logout/", "POST", {}, expected=204)
        owner.access = None
        session, _ = owner.request(
            "/api/v2/auth/login/",
            "POST",
            {"email": owner.email, "password": owner.password},
            auth=False,
        )
        owner.access, owner.csrf = session["access"], session["csrf_token"]
        owner.access = None  # Reload loses the in-memory access credential.
        owner.refresh()
        me, _ = owner.request("/api/v2/auth/me/")
        assert me["user"]["id"] == owner.user["id"]

        poll = draft(
            owner,
            question="Portfolio demonstration priorities",
            description="Synthetic recruiter journey, not real opinions.",
            results_visibility="after_voting",
            options=[
                {"option_text": "Security"},
                {"option_text": "User experience"},
            ],
        )
        poll = publish(owner, poll)
        url = PREFIX + poll["id"] + "/"
        listing, _ = guest.request(PREFIX + "?q=demonstration")
        assert listing["count"] == 1
        assert listing["results"][0]["id"] == poll["id"]
        detail, _ = guest.request(url)
        assert detail["status"] == "published"
        assert all(set(row) == {"id", "option_text"}
                   for row in detail["options"])
        first, second = [row["id"] for row in detail["options"]]
        guest.request(url + "ballots/", "POST", {}, expected=401)
        guest.request(url + "results/", expected=403)
        voter.request(url + "results/", expected=403)
        owner.request(url + "results/")  # Creator can always see aggregates.

        def state():
            return (
                Ballot.objects.count(),
                BallotSelection.objects.count(),
                AuditLog.objects.count(),
                Vote.objects.count(),
            )

        before = state()
        paused, _ = voter.request(
            url + "ballots/", "POST", {"option_ids": [first]}, expected=503
        )
        assert paused["error"]["code"] == "voting_paused"
        voter.request(
            "/api/polls/" + poll["id"] + "/vote/" + first + "/",
            "POST", {}, expected=503,
        )
        assert state() == before

        with override_settings(NEXUS_BALLOT_WRITES_ENABLED=True):
            receipt, _ = voter.request(
                url + "ballots/", "POST", {"option_ids": [first]}
            )
            replacement, _ = voter.request(
                url + "ballots/", "POST", {"option_ids": [second]}
            )
            assert replacement["submitted_at"] == receipt["submitted_at"]
            saved, _ = voter.request(url + "ballots/")
            assert saved["option_ids"] == [second]
            totals, _ = voter.request(url + "results/")
            assert totals["authority"] == authority
            assert totals["total_participants"] == 1
            assert totals["total_selections"] == 1
            assert {row["id"]: row["count"] for row in totals["options"]} == {
                first: 0, second: 1,
            }
            assert Ballot.objects.count() == 1
            assert BallotSelection.objects.count() == 1
            assert Vote.objects.count() == 0
            guest.request(url + "results/", expected=403)
            owner.request(
                url, "PATCH", {"question": "Must stay locked"}, expected=400
            )

        # Re-pausing writes preserves the accepted ballot and existing totals.
        before = state()
        voter.request(
            url + "ballots/", "POST", {"option_ids": [first]}, expected=503
        )
        assert state() == before
        saved, _ = voter.request(url + "ballots/")
        assert saved["option_ids"] == [second]
        for actor in (owner, voter):
            actor.request("/api/v2/auth/logout/", "POST", {}, expected=204)
            actor.access = None
            actor.refresh(expected=401)
            actor.request("/api/v2/auth/me/", expected=401)
