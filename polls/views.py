from django.db import transaction, models
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from .models import Poll, Option, Vote, AuditLog
from .permissions import CanAccessPoll
from .services import (
    PollExpiredError,
    get_poll,
    get_resource_or_404,
    private_response,
    require_active_user,
    visible_polls,
)
from rest_framework.views import APIView
from rest_framework.response import Response
from django.db.models import Count
from .serializers import (
    PollSerializer,
    PollCreateSerializer,
    PollDetailSerializer,
    OptionSerializer,
)
from django.core.cache import cache
from django.db.models import Prefetch
from rest_framework.decorators import api_view, permission_classes


def _invalidate_poll_cache(poll_id):
    cache_key = f"poll_results:{poll_id}"
    try:
        cache.delete(cache_key)
    except Exception:
        pass  # In-memory cache is unlikely to fail, but safe to ignore


def cast_vote(user, poll_id, option_id):
    """
    Cast a vote for a poll option.
    Supports single-choice and multiple-choice polls.
    """
    require_active_user(user)
    with transaction.atomic():
        poll = get_poll(user, poll_id, for_update=True)
        option = get_resource_or_404(
            Option.objects.select_for_update(), id=option_id, poll_id=poll_id
        )

        # Check poll expiration
        if poll.expires_at and poll.expires_at <= timezone.now():
            raise PollExpiredError("Poll expired")

        if poll.allow_multiple:
            # Multiple-choice: user can vote for multiple options
            vote, created = Vote.objects.get_or_create(
                user=user, option=option, poll=poll
            )
            if created:
                # Increment option's votes_count
                Option.objects.filter(id=option.id).update(
                    votes_count=models.F("votes_count") + 1
                )
                option.refresh_from_db(fields=["votes_count"])

                # Log the action
                log_action(
                    user=user,
                    action="Voted on poll (multi-choice)",
                    target_type="Poll",
                    target_id=poll_id,
                )
                _invalidate_poll_cache(poll_id)
            return vote, option.votes_count
        else:
            # Single-choice: only one vote per user
            existing_vote = (
                Vote.objects.select_for_update()
                .select_related('option')
                .filter(user=user, poll_id=poll_id)
                .first()
            )

            if existing_vote:
                old_option = existing_vote.option

                if old_option.id == option.id:
                    return existing_vote, old_option.votes_count  # No change

                # Decrement old option
                Option.objects.filter(id=old_option.id).update(
                    votes_count=models.F("votes_count") - 1
                )

                # Update vote record
                existing_vote.option = option
                existing_vote.save()

                # Increment new option
                Option.objects.filter(id=option.id).update(
                    votes_count=models.F("votes_count") + 1
                )
                option.refresh_from_db(fields=["votes_count"])

                # Logging and cache
                log_action(
                    user=user,
                    action="Changed vote on poll",
                    target_type="Poll",
                    target_id=poll_id,
                )
                _invalidate_poll_cache(poll_id)
                return existing_vote, option.votes_count

            # First-time vote
            vote = Vote.objects.create(user=user, poll=poll, option=option)
            Option.objects.filter(id=option.id).update(
                votes_count=models.F("votes_count") + 1
            )
            option.refresh_from_db(fields=["votes_count"])

            log_action(
                user=user,
                action="Voted on poll",
                target_type="Poll",
                target_id=poll_id,
            )
            _invalidate_poll_cache(poll_id)
            return vote, option.votes_count


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
                "votes_count": votes_count,
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
            Poll.objects.filter(is_public=True)
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
        log_action(
            user=self.request.user,
            action="Created poll",
            target_type="Poll",
            target_id=poll.id,
        )


class PollDetailView(
    LockedPollMutationMixin, generics.RetrieveUpdateDestroyAPIView
):
    queryset = (
        Poll.objects.all()
        .select_related("category", "created_by")
        .prefetch_related(
            Prefetch(
                "options",
                queryset=Option.objects.annotate(total_votes=Count("votes")),
            )
        )
    )
    serializer_class = PollDetailSerializer
    permission_classes = [CanAccessPoll]

    def get_queryset(self):
        return visible_polls(self.request.user, super().get_queryset())

    def get_object(self):
        if getattr(self, "_lock_mutation", False):
            poll = get_poll(
                self.request.user,
                self.kwargs["pk"],
                for_update=True,
                write=True,
            )
            self.check_object_permissions(self.request, poll)
        else:
            poll = super().get_object()
        self.accessed_poll = poll
        return poll

    def perform_update(self, serializer):
        poll = serializer.save()
        _invalidate_poll_cache(poll.id)
        log_action(
            user=self.request.user,
            action="Updated poll",
            target_type="Poll",
            target_id=poll.id,
        )

    def perform_destroy(self, instance):
        _invalidate_poll_cache(instance.id)
        log_action(
            user=self.request.user,
            action="Deleted poll",
            target_type="Poll",
            target_id=instance.id,
        )
        return super().perform_destroy(instance)


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
        option = serializer.save(poll=self.accessed_poll)
        log_action(
            user=self.request.user,
            action="Created option",
            target_type="Option",
            target_id=option.id,
        )


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
        if getattr(self, "_lock_mutation", False):
            parent_id = get_resource_or_404(
                Option.objects.only("poll_id"), pk=self.kwargs["pk"]
            ).poll_id
            poll = get_poll(
                self.request.user, parent_id, for_update=True, write=True
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


class PollResultsView(PrivatePollResponseMixin, APIView):
    permission_classes = [CanAccessPoll]

    def get(self, request, poll_id):
        poll = get_poll(request.user, poll_id)
        self.accessed_poll = poll
        options = (
            Option.objects.filter(poll_id=poll.pk)
            .annotate(total_votes=Count("votes"))
            .only("id", "option_text")
        )
        # B1 deliberately bypasses legacy payload caches and stored counters.
        options_list = [
            {
                "id": str(option.pk),
                "option_text": option.option_text,
                "votes_count": option.total_votes,
                "total_votes": option.total_votes,
            }
            for option in options
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
