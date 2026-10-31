"""Validated, disjoint voting cohorts during the immutable-Vote transition.

Callers hold the parent Poll lock for a consistent snapshot. Historical rows
are evidence, never a second writable voting store. No identities are emitted
by operational reports or public result payloads.
"""

import hashlib
from collections import Counter
from dataclasses import dataclass, field
from itertools import groupby

from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework.exceptions import APIException

from .models import AuditLog, Ballot, Vote


class HistoryUnavailable(APIException):
    status_code = 503
    default_detail = "Voting history requires reconciliation."
    default_code = "voting_history_unavailable"

    def __init__(self, reason):
        self.reason = reason
        super().__init__()


@dataclass(frozen=True)
class HistoricalGroup:
    options: frozenset
    submitted_at: object


@dataclass
class Ledger:
    options: dict
    history: dict
    ballots: dict
    counts: Counter = field(default_factory=Counter)
    participants: int = 0
    unconverted: int = 0


def authority():
    return settings.NEXUS_BALLOT_AUTHORITY


def validate_options(poll, selected, available, *, historical=False):
    """Apply the same cardinality rules to imported and native choices."""
    from rest_framework.exceptions import ValidationError

    reason = None
    if not selected or len(set(selected)) != len(selected):
        reason = "empty_or_duplicate_selections"
    elif not set(selected).issubset(available):
        reason = "cross_poll_or_missing_option"
    elif not poll.allow_multiple and len(selected) != 1:
        reason = "single_choice_multiple_selections"
    elif poll.allow_multiple and (
        len(selected) < poll.min_selections
        or (
            poll.max_selections is not None
            and len(selected) > poll.max_selections
        )
    ):
        reason = "selection_bounds"
    if reason:
        if historical:
            raise HistoryUnavailable(reason)
        raise ValidationError(
            {"option_ids": ["Invalid selection set: " + reason]}
        )


def historical_groups(poll, available, user_id=None):
    # A cross-poll row can otherwise disappear through the option-side join.
    if (
        Vote.objects.filter(option__poll_id=poll.pk)
        .exclude(poll_id=poll.pk)
        .exists()
    ):
        raise HistoryUnavailable("cross_poll_or_missing_option")
    query = Vote.objects.filter(poll_id=poll.pk)
    if user_id is not None:
        query = query.filter(user_id=user_id)
    rows = (
        query.order_by("user_id", "option_id", "id")
        .values_list("user_id", "option_id", "voted_at")
        .iterator(chunk_size=1000)
    )
    result = {}
    for user, entries in groupby(rows, key=lambda row: row[0]):
        entries = list(entries)
        selected = [row[1] for row in entries]
        validate_options(poll, selected, available, historical=True)
        timestamps = [row[2] for row in entries]
        if any(value is None for value in timestamps):
            raise HistoryUnavailable("missing_submission_time")
        result[user] = HistoricalGroup(frozenset(selected), min(timestamps))
    users = list(result)
    for offset in range(0, len(users), 1000):
        end = offset + 1000
        batch = users[offset:end]
        if get_user_model().objects.filter(pk__in=batch).count() != len(batch):
            raise HistoryUnavailable("missing_user")
    return result


PROOF_PREFIX = "Legacy ballot vote v1:"


def selection_proof(selected):
    material = ",".join(str(value) for value in sorted(selected))
    digest = hashlib.sha256(
        b"project-nexus:legacy-ballot:v1\0" + material.encode("ascii")
    ).hexdigest()
    return PROOF_PREFIX + digest


def ballot_proofs(ballot_ids):
    evidence = {}
    ids = list(ballot_ids)
    for offset in range(0, len(ids), 1000):
        end = offset + 1000
        for target, user, action, timestamp in AuditLog.objects.filter(
            target_type="Ballot",
            target_id__in=ids[offset:end],
            action__startswith=PROOF_PREFIX,
        ).values_list("target_id", "user_id", "action", "timestamp"):
            key = (target, user, action)
            if key not in evidence or timestamp > evidence[key]:
                evidence[key] = timestamp
    return evidence


def validate_ballot(poll, ballot, available, history, *, proofs=None):
    selections = list(ballot.selections.all())
    selected = [row.option_id for row in selections]
    if ballot.poll_id != poll.pk or any(
        row.poll_id != poll.pk or row.ballot_id != ballot.pk
        for row in selections
    ):
        raise HistoryUnavailable("cross_poll_or_missing_option")
    if ballot.source == "legacy":
        if history is None or ballot.submitted_at != history.submitted_at:
            raise HistoryUnavailable("legacy_provenance_conflict")
    elif ballot.source != "native" or history is not None:
        raise HistoryUnavailable("ballot_provenance_conflict")
    if ballot.submitted_at is None:
        if selected or history is not None:
            raise HistoryUnavailable("incomplete_ballot")
        return frozenset()
    validate_options(poll, selected, available, historical=True)
    if history is not None and frozenset(selected) != history.options:
        # A valid-sized subset can still be a partial historical conversion.
        # Only an exact, transactional F write receipt permits divergence.
        proofs = proofs if proofs is not None else ballot_proofs([ballot.pk])
        timestamp = proofs.get(
            (ballot.pk, ballot.user_id, selection_proof(selected))
        )
        if timestamp is None or timestamp < ballot.created_at:
            raise HistoryUnavailable("unproven_legacy_replacement")
    return frozenset(selected)


def snapshot(poll, *, require_ready=None):
    available = dict(
        poll.options.order_by("id").values_list("id", "option_text")
    )
    history = historical_groups(poll, available)
    ballots = {
        row.user_id: row
        for row in Ballot.objects.filter(poll_id=poll.pk)
        .prefetch_related("selections")
        .order_by("user_id")
    }
    ledger = Ledger(available, history, ballots)
    proofs = ballot_proofs(
        row.pk for row in ballots.values() if row.source == "legacy"
    )
    for user_id, ballot in ballots.items():
        selected = validate_ballot(
            poll, ballot, available, history.get(user_id), proofs=proofs
        )
        if ballot.submitted_at is not None:
            ledger.counts.update(selected)
            ledger.participants += 1
    for user_id, old in history.items():
        if user_id not in ballots:
            ledger.unconverted += 1
            ledger.counts.update(old.options)
            ledger.participants += 1
    if require_ready is None:
        require_ready = authority() == "ballots"
    if require_ready and ledger.unconverted:
        raise HistoryUnavailable("unconverted_history")
    # In ballot-only mode all counted cohorts are now submitted ballots.
    return ledger


def current_selection(poll, user_id, ledger=None):
    ledger = ledger or snapshot(poll)
    ballot = ledger.ballots.get(user_id)
    if ballot is not None:
        selected = validate_ballot(
            poll, ballot, ledger.options, ledger.history.get(user_id)
        )
        return ballot, selected, ballot.submitted_at
    old = ledger.history.get(user_id)
    if old:
        return None, old.options, old.submitted_at
    return None, frozenset(), None


def has_participated(poll, user):
    if user is None or not user.is_authenticated:
        return False
    _, _, submitted_at = current_selection(poll, user.pk)
    return submitted_at is not None


def results(poll):
    ledger = snapshot(poll)
    selections = sum(ledger.counts.values())
    return {
        "poll_id": str(poll.pk),
        "question": poll.question,
        "authority": authority(),
        "total_participants": ledger.participants,
        "total_selections": selections,
        "options": [
            {
                "id": str(option_id),
                "option_text": text,
                "count": ledger.counts[option_id],
                "percentage_of_participants": (
                    round(
                        100 * ledger.counts[option_id] / ledger.participants, 2
                    )
                    if ledger.participants
                    else 0
                ),
                "percentage_of_selections": (
                    round(100 * ledger.counts[option_id] / selections, 2)
                    if selections
                    else 0
                ),
            }
            for option_id, text in ledger.options.items()
        ],
    }
