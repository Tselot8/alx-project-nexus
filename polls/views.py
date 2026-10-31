from django.db import transaction
from django.utils import timezone
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from .models import Poll, Option, AuditLog
from . import management
from .policy import can_view_results, public_discovery
from .permissions import CanAccessPoll
from .services import (
    PollExpiredError,
    get_poll,
    get_resource_or_404,
    private_response,
    visible_polls,
)
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from .serializers import (
    PollSerializer,
    PollCreateSerializer,
    PollDetailSerializer,
    OptionSerializer,
)
from django.core.cache import cache
from rest_framework.decorators import api_view, permission_classes


def _invalidate_poll_cache(poll_id):
    cache_key = f"poll_results:{poll_id}"
    try:
        cache.delete(cache_key)
    except Exception:
        pass  # In-memory cache is unlikely to fail, but safe to ignore


def cast_vote(user, poll_id, option_id):
    """Legacy per-option adapter; Vote history is now immutable."""
    from .ballots import legacy_vote

    return legacy_vote(user, poll_id, option_id, clock=timezone.now)


def log_action(user, action, target_type, target_id):
    """
    Logs a user action for auditing purposes.

    Args:
        user: The user performing the action
        action: A string describing the action, e.g., "Created poll"
        target_type: The type of object affected,
            e.g., "Poll", "Option", "Vote"
        target_id: UUID of the object affected
    """
    AuditLog.objects.create(
        user=user, action=action, target_type=target_type, target_id=target_id
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@transaction.atomic
def vote_view(request, poll_id, option_id):
    try:
        vote, votes_count = cast_vote(
            user=request.user, poll_id=poll_id, option_id=option_id
        )

        response = Response(
            {
                "message": "Vote successful",
                "poll_id": str(poll_id),
                "option_id": str(option_id),
                "votes_count": (
                    votes_count
                    if can_view_results(request.user, vote.poll)
                    else None
                ),
            },
            status=200,
        )
        return private_response(response, vote.poll)

    except PollExpiredError as error:
        return Response({"error": str(error)}, status=400)


class PrivatePollResponseMixin:
    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(
            request, response, *args, **kwargs
        )
        poll = getattr(self, "accessed_poll", None)
        if poll is not None and 200 <= response.status_code < 300:
            private_response(response, poll)
        return response


class LockedPollMutationMixin(PrivatePollResponseMixin):
    """Only mutation handlers request locks, never HTML/OPTIONS rendering."""

    @transaction.atomic
    def retrieve(self, request, *args, **kwargs):
        self._lock_read = True
        try:
            return super().retrieve(request, *args, **kwargs)
        finally:
            self._lock_read = False

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        self._lock_mutation = True
        try:
            return super().update(request, *args, **kwargs)
        finally:
            self._lock_mutation = False

    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        self._lock_mutation = True
        try:
            return super().destroy(request, *args, **kwargs)
        finally:
            self._lock_mutation = False


class PollListCreateView(PrivatePollResponseMixin, generics.ListCreateAPIView):
    permission_classes = [CanAccessPoll]

    def get_queryset(self):
        return (
            public_discovery()
            .select_related("category", "created_by")
            .prefetch_related("options")
            .order_by("-created_at", "id")
        )

    def get_serializer_class(self):
        if self.request.method == "POST":
            return PollCreateSerializer
        return PollSerializer

    @transaction.atomic
    def perform_create(self, serializer):
        poll = serializer.save(created_by=self.request.user)
        self.accessed_poll = poll


class PollDetailView(
    LockedPollMutationMixin, generics.RetrieveUpdateDestroyAPIView
):
    queryset = (
        Poll.objects.all()
        .select_related("category", "created_by")
        .prefetch_related("options")
    )
    serializer_class = PollDetailSerializer
    permission_classes = [CanAccessPoll]

    def get_queryset(self):
        return visible_polls(self.request.user, super().get_queryset())

    def get_object(self):
        if getattr(self, "_lock_mutation", False) or getattr(
            self, "_lock_read", False
        ):
            poll = get_poll(
                self.request.user,
                self.kwargs["pk"],
                for_update=True,
                write=getattr(self, "_lock_mutation", False),
            )
            self.check_object_permissions(self.request, poll)
        else:
            poll = super().get_object()
        self.accessed_poll = poll
        return poll

    def perform_update(self, serializer):
        poll = serializer.save()
        _invalidate_poll_cache(poll.id)

    def perform_destroy(self, instance):
        management.delete_poll(self.request.user, instance.pk)
        _invalidate_poll_cache(instance.pk)


class OptionCreateView(PrivatePollResponseMixin, generics.CreateAPIView):
    serializer_class = OptionSerializer
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        self.accessed_poll = get_poll(
            request.user,
            self.kwargs["poll_id"],
            for_update=True,
            write=True,
        )
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        serializer.save(poll=self.accessed_poll)


class OptionUpdateDeleteView(
    LockedPollMutationMixin, generics.RetrieveUpdateDestroyAPIView
):
    queryset = Option.objects.select_related("poll")
    serializer_class = OptionSerializer
    permission_classes = [CanAccessPoll]

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .filter(poll__in=visible_polls(self.request.user))
        )

    def get_object(self):
        if getattr(self, "_lock_mutation", False) or getattr(
            self, "_lock_read", False
        ):
            parent_id = get_resource_or_404(
                Option.objects.only("poll_id"), pk=self.kwargs["pk"]
            ).poll_id
            poll = get_poll(
                self.request.user,
                parent_id,
                for_update=True,
                write=getattr(self, "_lock_mutation", False),
            )
            option = get_resource_or_404(
                Option.objects.select_for_update(),
                pk=self.kwargs["pk"],
                poll_id=poll.pk,
            )
            option.poll = poll
            self.check_object_permissions(self.request, option)
        else:
            option = super().get_object()
            poll = option.poll
        self.accessed_poll = poll
        return option

    def perform_destroy(self, instance):
        management.mutate_option(
            self.request.user,
            instance.poll_id,
            option_id=instance.pk,
            delete=True,
        )


class PollResultsView(PrivatePollResponseMixin, APIView):
    permission_classes = [CanAccessPoll]

    @transaction.atomic
    def get(self, request, poll_id):
        poll = get_poll(request.user, poll_id, for_update=True)
        if not can_view_results(request.user, poll):
            raise PermissionDenied("Results are not available to you.")
        self.accessed_poll = poll
        from .ledger import results

        aggregate = results(poll)
        options_list = [
            {
                "id": row["id"],
                "option_text": row["option_text"],
                "votes_count": row["count"],
                "total_votes": row["count"],
            }
            for row in aggregate["options"]
        ]
        return Response(
            {
                "poll_id": str(poll.pk),
                "question": poll.question,
                "options": options_list,
                "total_votes": sum(
                    item["total_votes"] for item in options_list
                ),
            }
        )
