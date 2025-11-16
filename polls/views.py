from django.db import transaction, models
from rest_framework import generics, permissions
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
from django.db.models import Count
from rest_framework import status

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

        existing_vote = Vote.objects.select_for_update().filter(
            user=user, poll_id=poll_id
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

        _invalidate_poll_cache(poll_id)
        return vote, new_option.votes_count

class PollListCreateView(generics.ListCreateAPIView):
    queryset = Poll.objects.all().select_related('category', 'created_by')
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return PollCreateSerializer
        return PollSerializer
    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class PollDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Poll.objects.all().select_related('category', 'created_by')
    serializer_class = PollDetailSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_update(self, serializer):
        serializer.save()


# ---- OPTIONS ----

class OptionCreateView(generics.CreateAPIView):
    serializer_class = OptionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        poll_id = self.kwargs['poll_id']
        poll = get_object_or_404(Poll, id=poll_id)
        serializer.save(poll=poll)


class OptionUpdateDeleteView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Option.objects.all()
    serializer_class = OptionSerializer
    permission_classes = [permissions.IsAuthenticated]

class PollResultsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def _get_results_queryset(self, poll_id):
        # Annotate the options with total_votes (Count on related votes)
        options_qs = Option.objects.filter(poll_id=poll_id).annotate(
            total_votes=Count('votes')
        ).only('id', 'option_text', 'votes_count')

        # Load poll with minimal fields
        poll_qs = Poll.objects.filter(id=poll_id).only('id', 'question', 'description', 'allow_multiple', 'is_public', 'expires_at', 'created_at', 'updated_at')
        return poll_qs.first(), options_qs

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
