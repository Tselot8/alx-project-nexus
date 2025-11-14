from django.db import transaction, models
from rest_framework import generics, permissions
from django.utils import timezone
from django.shortcuts import get_object_or_404
from .models import Poll, Option, Vote
from .serializers import (
    PollSerializer,
    PollCreateSerializer,
    PollDetailSerializer,
    OptionSerializer
)

def cast_vote(user, poll_id, option_id):
    with transaction.atomic():
        poll = get_object_or_404(Poll.objects.select_for_update(), id=poll_id)

        # If expired
        if poll.expires_at and poll.expires_at < timezone.now():
            raise ValueError("Poll expired")

        option = get_object_or_404(
            Option.objects.select_for_update(),
            id=option_id,
            poll_id=poll_id
        )

        existing_vote = Vote.objects.select_for_update().filter(
            user=user, poll_id=poll_id
        ).first()

        # If user already voted → adjust vote
        if existing_vote:
            if existing_vote.option.id == option_id:
                return existing_vote, existing_vote.option.votes_count  # no change

            # decrement old option
            existing_vote.option.votes_count = models.F("votes_count") - 1
            existing_vote.option.save(update_fields=["votes_count"])

            # update vote record
            existing_vote.option = option
            existing_vote.save()

            # increment new option
            option.votes_count = models.F("votes_count") + 1
            option.save(update_fields=["votes_count"])
            option.refresh_from_db(fields=["votes_count"])

            return existing_vote, option.votes_count

        # Else: first-time vote
        vote = Vote.objects.create(user=user, poll=poll, option=option)
        option.votes_count = models.F("votes_count") + 1
        option.save(update_fields=["votes_count"])
        option.refresh_from_db(fields=["votes_count"])

        return vote, option.votes_count

class PollListCreateView(generics.ListCreateAPIView):
    queryset = Poll.objects.all().select_related('category', 'created_by')
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return PollCreateSerializer
        return PollSerializer


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
        serializer.save(poll_id=poll_id)


class OptionUpdateDeleteView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Option.objects.all()
    serializer_class = OptionSerializer
    permission_classes = [permissions.IsAuthenticated]

