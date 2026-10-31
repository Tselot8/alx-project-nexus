"""One transactional write path for v2, legacy adapters and imports."""

from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException

from .ledger import (
    HistoryUnavailable,
    current_selection,
    historical_groups,
    snapshot,
    selection_proof,
    validate_ballot,
    validate_options,
)
from .models import AuditLog, Ballot, BallotSelection, Option, Poll
from .services import (
    PollExpiredError,
    get_poll,
    get_resource_or_404,
    require_active_user,
)


class WritesPaused(APIException):
    status_code = 503
    default_detail = "Voting is paused during the voting-store transition."
    default_code = "voting_paused"


@dataclass
class LegacyReceipt:
    """Response adapter, deliberately not a newly written Vote model."""

    poll: Poll
    option: Option
    user: object
    id: object


def require_writes():
    if not settings.NEXUS_BALLOT_WRITES_ENABLED:
        raise WritesPaused()


def lock_configuration(poll):
    if poll.configuration_locked is not True:
        poll.configuration_locked = True
        poll.version += 1
        # Voting must not expose first-participation timing as a content edit.
        poll.save(update_fields=["configuration_locked", "version"])


def import_group(poll, user_id):
    """Parent lock required. Idempotent; source rows are never changed."""
    available = dict(poll.options.values_list("id", "option_text"))
    history = historical_groups(poll, available, user_id)
    old = history.get(user_id)
    existing = (
        Ballot.objects.select_for_update()
        .filter(poll=poll, user_id=user_id)
        .prefetch_related("selections")
        .first()
    )
    if existing is not None:
        validate_ballot(poll, existing, available, old)
        return existing, False
    if old is None:
        return None, False
    ballot = Ballot.objects.create(
        poll=poll,
        user_id=user_id,
        source="legacy",
        submitted_at=old.submitted_at,
    )
    BallotSelection.objects.bulk_create(
        [
            BallotSelection(ballot=ballot, poll=poll, option_id=option_id)
            for option_id in sorted(old.options)
        ]
    )
    lock_configuration(poll)
    return ballot, True


@transaction.atomic
def submit(user, poll_id, option_ids, *, legacy=False, clock=None):
    require_active_user(user)
    poll = get_poll(user, poll_id, for_update=True)
    if legacy:
        # Preserve legacy option association/missing-resource checks before
        # eligibility errors, including creator-readable incomplete drafts.
        get_resource_or_404(
            Option.objects.select_for_update().filter(poll=poll),
            pk=option_ids[0],
        )
    # Share credentials deliberately do not authorize participation.
    if poll.expires_at and poll.expires_at <= (clock or timezone.now)():
        raise PollExpiredError("Poll expired")
    if poll.status != Poll.Status.PUBLISHED:
        raise PollExpiredError("Poll is not open for voting")
    require_writes()
    options = dict(
        Option.objects.select_for_update()
        .filter(poll=poll)
        .order_by("id")
        .values_list("id", "option_text")
    )
    if legacy:
        if poll.allow_multiple and (
            poll.min_selections != 1 or poll.max_selections is not None
        ):
            raise PollExpiredError(
                "This configuration requires complete-ballot voting."
            )
    ledger = snapshot(poll)
    ballot, previous, _ = current_selection(poll, user.pk, ledger)
    selected = list(option_ids)
    if legacy and poll.allow_multiple:
        selected = list(previous | set(selected))
    validate_options(poll, selected, options)
    selected = frozenset(selected)
    # Option locks and historical validation may take time even after the
    # parent is locked. Decide eligibility again immediately before writing.
    accepted_at = (clock or timezone.now)()
    if poll.expires_at and poll.expires_at <= accepted_at:
        raise PollExpiredError("Poll expired")
    # Validate the complete poll ledger before making any writes. Invalid
    # historic groups quarantine the poll rather than yielding partial totals.
    ballot, _ = import_group(poll, user.pk)
    if ballot is not None and ballot.submitted_at is not None:
        if previous == selected:
            lock_configuration(poll)
            return ballot, poll, ledger.counts
    if ballot is None:
        ballot = Ballot.objects.create(poll=poll, user=user)
    ballot.selections.all().delete()
    BallotSelection.objects.bulk_create(
        [
            BallotSelection(ballot=ballot, poll=poll, option_id=option_id)
            for option_id in sorted(selected)
        ]
    )
    if ballot.submitted_at is None:
        ballot.submitted_at = accepted_at
    ballot.save(update_fields=["submitted_at", "updated_at"])
    lock_configuration(poll)
    AuditLog.objects.create(
        user=user,
        action=(
            selection_proof(selected)
            if ballot.source == "legacy"
            else ("Changed vote on poll" if previous else "Voted on poll")
        ),
        target_type="Ballot" if ballot.source == "legacy" else "Poll",
        target_id=ballot.pk if ballot.source == "legacy" else poll.pk,
    )
    counts = snapshot(poll).counts
    # Derived compatibility projection only; results never trust this cache.
    for option_id in options:
        Option.objects.filter(pk=option_id).update(
            votes_count=counts[option_id]
        )
    return ballot, poll, counts


def legacy_vote(user, poll_id, option_id, *, clock=None):
    ballot, poll, counts = submit(
        user, poll_id, [option_id], legacy=True, clock=clock
    )
    option = Option.objects.get(pk=option_id, poll=poll)
    return LegacyReceipt(poll, option, user, ballot.pk), counts[option_id]


@transaction.atomic
def backfill_group(poll_id, user_id, *, apply=False):
    # Operational caller, not an API authorization boundary.
    poll = Poll.objects.select_for_update().get(pk=poll_id)
    if apply:
        require_writes()
    available = dict(poll.options.values_list("id", "option_text"))
    old = historical_groups(poll, available, user_id).get(user_id)
    if old is None:
        raise HistoryUnavailable("missing_source_group")
    existing = (
        Ballot.objects.filter(poll=poll, user_id=user_id)
        .prefetch_related("selections")
        .first()
    )
    if existing:
        validate_ballot(poll, existing, available, old)
        return "already_converted"
    if not apply:
        return "would_convert"
    import_group(poll, user_id)
    return "converted"
