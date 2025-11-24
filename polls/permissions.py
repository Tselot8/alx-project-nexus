from rest_framework import permissions

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
