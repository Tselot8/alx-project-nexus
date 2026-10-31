"""Shared lifecycle, access and results policy for both API generations."""

import hashlib
import re

from django.db.models import Q
from django.http import Http404
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from rest_framework.exceptions import ValidationError

from .models import AuditLog, Ballot, Poll, PollShareToken, Vote
from .services import is_poll_owner

TOKEN_PATTERN = re.compile(r"\A[A-Za-z0-9_-]{43}\Z")
LOCKED_FIELDS = {
    "question",
    "is_public",
    "allow_multiple",
    "results_visibility",
    "min_selections",
    "max_selections",
}


def effective_status(poll, now=None):
    now = now or timezone.now()
    if (
        poll.status == Poll.Status.PUBLISHED
        and poll.expires_at is not None
        and poll.expires_at <= now
    ):
        return Poll.Status.CLOSED
    return poll.status


def public_discovery(queryset=None):
    queryset = queryset if queryset is not None else Poll.objects.all()
    return queryset.filter(
        is_public=True, status__in=[Poll.Status.PUBLISHED, Poll.Status.CLOSED]
    )


def vote_evidence(poll):
    return (
        Vote.objects.filter(
            Q(poll_id=poll.pk) | Q(option__poll_id=poll.pk)
        ).exists()
        or AuditLog.objects.filter(
            target_type__iexact="Poll",
            target_id=poll.pk,
            action__icontains="vote",
        ).exists()
        or Ballot.objects.filter(
            poll_id=poll.pk, submitted_at__isnull=False
        ).exists()
    )


def configuration_is_locked(poll):
    # NULL is unknown forever until confirmed voted, never an unlocked value.
    return poll.configuration_locked is not False or vote_evidence(poll)


def ensure_mutable(poll):
    if poll.status == Poll.Status.ARCHIVED:
        raise ValidationError({"poll": ["Archived polls are read-only."]})


def check_configuration_edit(poll, changed_fields):
    ensure_mutable(poll)
    if set(changed_fields) & (LOCKED_FIELDS | {"options"}):
        if configuration_is_locked(poll):
            raise ValidationError(
                {
                    "configuration": [
                        "Configuration is locked by voting or unknown history."
                    ]
                }
            )


def can_view_results(user, poll):
    if is_poll_owner(user, poll):
        return True
    if poll.results_visibility == Poll.ResultsVisibility.IMMEDIATE:
        return True
    if poll.results_visibility == Poll.ResultsVisibility.AFTER_CLOSING:
        return effective_status(poll) in {
            Poll.Status.CLOSED,
            Poll.Status.ARCHIVED,
        }
    return bool(
        user is not None
        and user.is_authenticated
        and Vote.objects.filter(
            user_id=user.pk,
            poll_id=poll.pk,
            option__poll_id=poll.pk,
        ).exists()
    )


@sensitive_variables()
def share_digest(raw):
    if not isinstance(raw, str) or not TOKEN_PATTERN.fullmatch(raw):
        return None
    return hashlib.sha256(
        b"project-nexus:poll-share:v1\0" + raw.encode("ascii")
    ).hexdigest()


@sensitive_variables()
def valid_share(poll, raw):
    digest = share_digest(raw)
    return bool(
        digest
        and not poll.is_public
        and poll.status != Poll.Status.DRAFT
        and PollShareToken.objects.filter(
            poll_id=poll.pk,
            token_digest=digest,
        ).exists()
    )


@sensitive_variables()
def authorize_read(user, poll, raw_share=None):
    if is_poll_owner(user, poll):
        return
    if poll.status == Poll.Status.DRAFT:
        raise Http404("Not found.")
    if poll.is_public or valid_share(poll, raw_share):
        return
    raise Http404("Not found.")
