from django.db import transaction, models
from rest_framework import generics, permissions, status
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.shortcuts import get_object_or_404
from .models import Poll, Option, Vote
from rest_framework.views import APIView
from rest_framework.response import Response
from django.db.models import Count, F
from .serializers import (
    PollSerializer,
    PollCreateSerializer,
    PollDetailSerializer,
    OptionSerializer,
    PollResultsSerializer
)
from django.core.cache import cache
from django.db.models import Prefetch
from rest_framework.decorators import api_view, permission_classes

def _invalidate_poll_cache(poll_id):
    cache_key = f"poll_results:{poll_id}"
    cache.delete(cache_key)

def cast_vote(user, poll_id, option_id):
    with transaction.atomic():
        poll = get_object_or_404(Poll.objects.select_for_update(), id=poll_id)

        if poll.expires_at and poll.expires_at < timezone.now():
            raise ValueError("Poll expired")

        new_option = get_object_or_404(
            Option.objects.select_for_update(),
            id=option_id,
            poll_id=poll_id
        )

        existing_vote = Vote.objects.select_for_update(
        ).select_related('option').filter(user=user, poll_id=poll_id
        ).first()

        if existing_vote:
            old_option = existing_vote.option

            if old_option.id == new_option.id:
                return existing_vote, old_option.votes_count  # no change

            # decrement old option
            Option.objects.filter(id=old_option.id).update(
                votes_count=models.F("votes_count") - 1
            )

            # update vote record
            existing_vote.option = new_option
            existing_vote.save()

            # increment new option
            Option.objects.filter(id=new_option.id).update(
                votes_count=models.F("votes_count") + 1
            )
            new_option.refresh_from_db(fields=["votes_count"])

            _invalidate_poll_cache(poll_id)
            return existing_vote, new_option.votes_count

        # First-time vote
        vote = Vote.objects.create(user=user, poll=poll, option=new_option)
        Option.objects.filter(id=new_option.id).update(
            votes_count=models.F("votes_count") + 1
        )
        new_option.refresh_from_db(fields=["votes_count"])
        
        log_action(
            user=user,
            action="Voted on poll",
            target_type="Poll",
            target_id=poll_id
        )

        _invalidate_poll_cache(poll_id)
        return vote, new_option.votes_count

from .models import AuditLog

def log_action(user, action, target_type, target_id):
    """
    Logs a user action for auditing purposes.

    Args:
        user: The user performing the action
        action: A string describing the action, e.g., "Created poll"
        target_type: The type of object affected, e.g., "Poll", "Option", "Vote"
        target_id: UUID of the object affected
    """
    AuditLog.objects.create(
        user=user,
        action=action,
        target_type=target_type,
        target_id=target_id
    )

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def vote_view(request, poll_id, option_id):
    try:
        vote, votes_count = cast_vote(
            user=request.user,
            poll_id=poll_id,
            option_id=option_id
        )

        return Response({
            "message": "Vote successful",
            "poll_id": poll_id,
            "option_id": option_id,
            "votes_count": votes_count
        }, status=200)

    except ValueError as e:
        return Response({"error": str(e)}, status=400)

    except Exception as e:
        return Response({"error": "Unexpected error"}, status=500)

class PollListCreateView(generics.ListCreateAPIView):
    queryset = Poll.objects.all().select_related('category', 'created_by').prefetch_related('options')
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return PollCreateSerializer
        return PollSerializer
    def perform_create(self, serializer):
        poll = serializer.save(created_by=self.request.user)
        log_action(
                user=self.request.user,
                action="Created poll",
                target_type="Poll",
                target_id=poll.id
            )


class PollDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Poll.objects.all().select_related('category', 'created_by').prefetch_related(
        Prefetch('options', queryset=Option.objects.annotate(total_votes=Count('votes')))
    )
    serializer_class = PollDetailSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_update(self, serializer):
        poll = serializer.save()
        _invalidate_poll_cache(poll.id)
        log_action(
            user=self.request.user,
            action="Updated poll",
            target_type="Poll",
            target_id=poll.id
        )
    def perform_destroy(self, instance):
        _invalidate_poll_cache(instance.id)  # ADD THIS
        log_action(
            user=self.request.user,
            action="Deleted poll",
            target_type="Poll",
            target_id=instance.id
        )
        return super().perform_destroy(instance)



# ---- OPTIONS ----

class OptionCreateView(generics.CreateAPIView):
    serializer_class = OptionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        poll_id = self.kwargs['poll_id']
        poll = get_object_or_404(Poll, id=poll_id)
        option = serializer.save(poll=poll)
        log_action(
            user=self.request.user,
            action="Created option",
            target_type="Option",
            target_id=option.id
        )


class OptionUpdateDeleteView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Option.objects.all()
    serializer_class = OptionSerializer
    permission_classes = [permissions.IsAuthenticated]

class PollResultsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def _get_results_queryset(self, poll_id):
        options_qs = Option.objects.filter(poll_id=poll_id).annotate(
            total_votes=Count('votes')
        ).only('id', 'option_text', 'votes_count')

        poll = Poll.objects.filter(id=poll_id).select_related('category', 'created_by').prefetch_related(
            Prefetch('options', queryset=options_qs)
        ).only('id','question','description','allow_multiple','is_public','expires_at','created_at','updated_at').first()

        return poll, list(poll.options.all()) if poll else (None, options_qs)


    def get(self, request, poll_id):
        # Try cache first (see caching section below)
        cache_key = f"poll_results:{poll_id}"
        cached = cache.get(cache_key)
        if cached:
            return Response(cached)

        poll, options_qs = self._get_results_queryset(poll_id)
        if not poll:
            return Response({"detail": "Poll not found"}, status=status.HTTP_404_NOT_FOUND)

        # Build payload
        options_list = [
            {
                "id": str(o.id),
                "option_text": o.option_text,
                "votes_count": o.votes_count,
                "total_votes": o.total_votes
            }
            for o in options_qs
        ]
        payload = {
            "poll_id": str(poll.id),
            "question": poll.question,
            "options": options_list,
            "total_votes": sum(o["total_votes"] for o in options_list)
        }

        # Set cache
        cache.set(cache_key, payload, timeout=15)  # short TTL for near-real-time
        return Response(payload)
