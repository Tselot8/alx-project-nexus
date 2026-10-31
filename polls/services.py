"""Shared access rules for the legacy API; no share-token access exists yet."""

from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils.cache import patch_cache_control
from rest_framework.exceptions import NotAuthenticated, PermissionDenied

from .models import Poll


class PollExpiredError(ValueError):
    """Expected legacy voting rejection; retain ValueError compatibility."""


def is_poll_owner(user, poll):
    return bool(
        user is not None
        and user.is_authenticated
        and user.pk == poll.created_by_id
    )


def require_active_user(user):
    if (
        user is None
        or not user.is_authenticated
        or not getattr(user, "is_active", False)
    ):
        raise NotAuthenticated("An active authenticated account is required.")


def visible_polls(user, queryset=None):
    if queryset is None:
        queryset = Poll.objects.all()
    condition = Q(is_public=True)
    if user is not None and user.is_authenticated:
        condition |= Q(created_by_id=user.pk)
    return queryset.filter(condition)


def authorize_poll(user, poll, *, write=False):
    owner = is_poll_owner(user, poll)
    if not poll.is_public and not owner:
        raise Http404("Not found.")
    if write:
        require_active_user(user)
        if not owner:
            raise PermissionDenied("Only the creator may modify this poll.")


def get_resource_or_404(queryset, **lookup):
    try:
        return get_object_or_404(queryset, **lookup)
    except Http404:
        # Do not distinguish a hidden parent from a missing option.
        raise Http404("Not found.") from None


def get_poll(user, poll_id, *, for_update=False, write=False):
    queryset = visible_polls(user)
    if for_update:
        queryset = queryset.select_for_update()
    poll = get_resource_or_404(queryset, pk=poll_id)
    authorize_poll(user, poll, write=write)
    return poll


def private_response(response, poll):
    if not poll.is_public:
        patch_cache_control(response, private=True, no_store=True)
    return response
