from rest_framework import permissions


from .models import Option
from .services import authorize_poll


class CanAccessPoll(permissions.IsAuthenticatedOrReadOnly):
    """Public reads, creator-only private access and mutations."""

    def has_object_permission(self, request, view, obj):
        poll = obj.poll if isinstance(obj, Option) else obj
        authorize_poll(
            request.user,
            poll,
            write=request.method not in permissions.SAFE_METHODS,
        )
        return True


class IsPollOwner(permissions.BasePermission):
    """
    Only the user who created the poll can update or delete it.
    """

    def has_object_permission(self, request, view, obj):
        return obj.created_by == request.user


class IsPollOwnerForOption(permissions.BasePermission):
    """
    Only the owner of the poll can add options.
    """

    def has_permission(self, request, view):
        poll_id = view.kwargs.get("poll_id")
        from .models import Poll

        poll = Poll.objects.filter(id=poll_id).first()
        return poll and poll.created_by == request.user


class IsCommentOwner(permissions.BasePermission):
    """
    Only the owner of the comment can delete it.
    """

    def has_object_permission(self, request, view, obj):
        return obj.user == request.user
