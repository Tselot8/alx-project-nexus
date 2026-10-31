"""Transactional poll writers; Vote remains authoritative until F."""

import secrets
import unicodedata

from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from rest_framework.exceptions import APIException, ValidationError

from .models import AuditLog, Option, Poll, PollShareToken
from .policy import (
    LOCKED_FIELDS,
    check_configuration_edit,
    configuration_is_locked,
    effective_status,
    ensure_mutable,
    share_digest,
    vote_evidence,
)
from .services import get_poll, require_active_user


class Conflict(APIException):
    status_code = 409
    default_detail = "The operation conflicts with the current state."
    default_code = "conflict"


def audit(user, poll, action):
    AuditLog.objects.create(
        user=user,
        action=action,
        target_type="Poll",
        target_id=poll.pk,
    )


def normalized_option(text):
    return unicodedata.normalize("NFKC", text.strip()).casefold()


def validate_limits(poll):
    if poll.min_selections < 1:
        raise ValidationError(
            {"min_selections": ["Minimum must be at least 1."]}
        )
    if poll.max_selections is not None:
        if poll.max_selections < poll.min_selections:
            raise ValidationError(
                {"max_selections": ["Maximum is below minimum."]}
            )
    if not poll.allow_multiple and (
        poll.min_selections != 1 or poll.max_selections not in (None, 1)
    ):
        raise ValidationError(
            {"voting_mode": ["Single-choice limits must be 1."]}
        )


def validate_publication(poll, *, require_future=True):
    validate_limits(poll)
    texts = list(poll.options.values_list("option_text", flat=True))
    normalized = [normalized_option(text) for text in texts]
    if not poll.question.strip():
        raise ValidationError({"question": ["A question is required."]})
    if len(texts) < 2 or any(not value for value in normalized):
        raise ValidationError(
            {"options": ["Provide at least two nonblank options."]}
        )
    if len(set(normalized)) != len(normalized):
        raise ValidationError({"options": ["Options must be distinct."]})
    if poll.min_selections > len(texts) or (
        poll.max_selections is not None and poll.max_selections > len(texts)
    ):
        raise ValidationError(
            {"max_selections": ["Limits exceed available options."]}
        )
    if (
        require_future
        and poll.expires_at is not None
        and poll.expires_at <= timezone.now()
    ):
        raise ValidationError(
            {"expires_at": ["Choose a future closing date."]}
        )


def persist_mutation(poll):
    # Called only under the parent Poll lock.
    if poll.configuration_locked is not True and vote_evidence(poll):
        poll.configuration_locked = True
    poll.version += 1
    poll.save()


def materialize_expiration(poll):
    poll.status = effective_status(poll)


@transaction.atomic
def create_poll(user, data, *, legacy=False):
    require_active_user(user)
    options = data.pop("options", [])
    if len(options) > 100:
        raise ValidationError(
            {"options": ["At most 100 options are supported."]}
        )
    poll = Poll(
        created_by=user,
        configuration_locked=False,
        status=Poll.Status.PUBLISHED if legacy else Poll.Status.DRAFT,
        **data,
    )
    validate_limits(poll)
    poll.save(force_insert=True)
    for option in options:
        Option.objects.create(poll=poll, **option)
    if legacy:
        validate_publication(poll)
    audit(user, poll, "Created poll")
    return poll


@transaction.atomic
def update_poll(user, poll_id, data):
    poll = get_poll(user, poll_id, for_update=True, write=True)
    changed = {
        key for key, value in data.items() if getattr(poll, key) != value
    }
    check_configuration_edit(poll, changed)
    previous_public = poll.is_public
    materialize_expiration(poll)
    for key, value in data.items():
        setattr(poll, key, value)
    validate_limits(poll)
    if poll.status == Poll.Status.PUBLISHED and changed & LOCKED_FIELDS:
        validate_publication(poll)
    # An explicitly provided past date is invalid. Expired historical dates
    # may remain unchanged while editing description/category of a closed poll.
    if (
        "expires_at" in changed
        and poll.expires_at is not None
        and poll.expires_at <= timezone.now()
    ):
        raise ValidationError(
            {"expires_at": ["Choose a future closing date."]}
        )
    if previous_public != poll.is_public:
        PollShareToken.objects.filter(poll=poll).update(
            token_digest=None,
            generation=F("generation") + 1,
            updated_at=timezone.now(),
        )
    # Even a no-op PATCH can materialize an expired published state.
    stored_status = Poll.objects.values_list("status", flat=True).get(
        pk=poll.pk
    )
    if changed or stored_status != poll.status:
        persist_mutation(poll)
        audit(user, poll, "Updated poll")
    return poll


@transaction.atomic
def delete_poll(user, poll_id):
    poll = get_poll(user, poll_id, for_update=True, write=True)
    if poll.status != Poll.Status.DRAFT or configuration_is_locked(poll):
        raise ValidationError(
            {"poll": ["Only verified, unvoted drafts may be deleted."]}
        )
    audit(user, poll, "Deleted draft")
    poll.delete()


@transaction.atomic
def mutate_option(user, poll_id, data=None, *, option_id=None, delete=False):
    poll = get_poll(user, poll_id, for_update=True, write=True)
    check_configuration_edit(poll, {"options"})
    materialize_expiration(poll)
    if option_id is None:
        if poll.options.count() >= 100:
            raise ValidationError(
                {"options": ["At most 100 options are supported."]}
            )
        option = Option.objects.create(poll=poll, **data)
    else:
        from .services import get_resource_or_404

        option = get_resource_or_404(
            Option.objects.select_for_update(), pk=option_id, poll_id=poll.pk
        )
        if delete:
            option.delete()
        else:
            option.option_text = data["option_text"]
            option.save(update_fields=["option_text"])
    if poll.status == Poll.Status.PUBLISHED:
        validate_publication(poll)
    persist_mutation(poll)
    audit(user, poll, "Deleted option" if delete else "Updated options")
    return poll, None if delete else option


@transaction.atomic
def transition(user, poll_id, action, data=None):
    poll = get_poll(user, poll_id, for_update=True, write=True)
    ensure_mutable(poll)
    current = effective_status(poll)
    if action == "publish" and current == Poll.Status.DRAFT:
        validate_publication(poll)
        poll.status = Poll.Status.PUBLISHED
    elif action == "close" and poll.status == Poll.Status.PUBLISHED:
        poll.status = Poll.Status.CLOSED
    elif action == "reopen" and current == Poll.Status.CLOSED:
        if data is None or "expires_at" not in data:
            raise ValidationError(
                {
                    "expires_at": [
                        "Choose a future date or explicitly remove expiration."
                    ]
                }
            )
        poll.expires_at = data["expires_at"]
        validate_publication(poll)
        poll.status = Poll.Status.PUBLISHED
    elif action == "archive" and current in {
        Poll.Status.PUBLISHED,
        Poll.Status.CLOSED,
    }:
        poll.status = Poll.Status.ARCHIVED
    else:
        raise ValidationError({"status": ["Invalid lifecycle transition."]})
    persist_mutation(poll)
    audit(user, poll, "Poll " + action)
    return poll


@transaction.atomic
@sensitive_variables()
def change_share(user, poll_id, action):
    poll = get_poll(user, poll_id, for_update=True, write=True)
    if poll.is_public:
        raise ValidationError(
            {"visibility": ["Only private polls use share links."]}
        )
    record = PollShareToken.objects.filter(poll=poll).first()
    if action == "revoke":
        # Revocation is credential security, not an archived-content edit.
        if record and record.token_digest is not None:
            record.token_digest = None
            record.generation += 1
            record.save(
                update_fields=["token_digest", "generation", "updated_at"]
            )
        return poll, record, None
    if effective_status(poll) not in {
        Poll.Status.PUBLISHED,
        Poll.Status.CLOSED,
    }:
        raise ValidationError(
            {"status": ["Only published or closed polls can issue links."]}
        )
    if action == "issue" and record and record.token_digest is not None:
        raise Conflict("A link is active; regenerate it to replace it.")
    raw = secrets.token_urlsafe(32)
    if record is None:
        record = PollShareToken(poll=poll)
    else:
        record.generation += 1
    record.token_digest = share_digest(raw)
    record.save()
    return poll, record, raw
