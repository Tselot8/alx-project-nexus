from collections.abc import Mapping

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers, generics, permissions
from .models import Poll, Option
from . import management
from .policy import can_view_results
from .services import get_poll
from .ledger import snapshot


class RejectProtectedFields:
    protected_input_fields = ()

    def to_internal_value(self, data):
        if isinstance(data, Mapping):
            errors = {
                field: ["This field is read-only."]
                for field in self.protected_input_fields
                if field in data
            }
            if errors:
                raise serializers.ValidationError(errors)
        return super().to_internal_value(data)


POLL_METADATA = (
    "id",
    "created_by",
    "created_by_id",
    "created_at",
    "updated_at",
)


class OptionSerializer(RejectProtectedFields, serializers.ModelSerializer):
    protected_input_fields = ("id", "poll", "poll_id", "votes_count")

    class Meta:
        model = Option
        fields = ['id', 'option_text', 'votes_count']
        read_only_fields = ['id', 'votes_count']

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        user = request.user if request else None
        results = self.context.setdefault("_results_counts", {})
        if instance.poll_id not in results:
            with transaction.atomic():
                poll = get_poll(user, instance.poll_id, for_update=True)
                results[poll.pk] = (
                    snapshot(poll).counts
                    if can_view_results(user, poll)
                    else None
                )
        counts = results[instance.poll_id]
        data["votes_count"] = (
            counts[instance.pk] if counts is not None else None
        )
        return data

    def create(self, validated_data):
        poll = validated_data.pop("poll")
        _, option = management.mutate_option(
            self.context["request"].user, poll.pk, validated_data
        )
        return option

    def update(self, instance, validated_data):
        _, option = management.mutate_option(
            self.context["request"].user,
            instance.poll_id,
            validated_data,
            option_id=instance.pk,
        )
        return option


class OptionCreateView(generics.CreateAPIView):
    serializer_class = OptionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        poll_id = self.kwargs["poll_id"]
        poll = get_object_or_404(Poll, id=poll_id)
        serializer.save(poll=poll)


class PollSerializer(RejectProtectedFields, serializers.ModelSerializer):
    protected_input_fields = POLL_METADATA

    class Meta:
        model = Poll
        fields = [
            'id',
            'question',
            'description',
            'category',
            'created_by',
            'is_public',
            'allow_multiple',
            'expires_at',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at']


class PollCreateSerializer(RejectProtectedFields, serializers.ModelSerializer):
    protected_input_fields = POLL_METADATA

    options = OptionSerializer(many=True)
    permission_classes = [permissions.IsAuthenticated]

    class Meta:
        model = Poll
        fields = [
            'id',
            'question',
            'description',
            'category',
            'is_public',
            'allow_multiple',
            'expires_at',
            'options',
        ]
        read_only_fields = ['id']

    @transaction.atomic
    def create(self, validated_data):
        user = validated_data.pop("created_by")
        return management.create_poll(user, validated_data, legacy=True)


class PollDetailSerializer(RejectProtectedFields, serializers.ModelSerializer):
    protected_input_fields = POLL_METADATA + ("options",)

    options = OptionSerializer(many=True, read_only=True)

    class Meta:
        model = Poll
        fields = [
            'id',
            'question',
            'description',
            'category',
            'created_by',
            'is_public',
            'allow_multiple',
            'expires_at',
            'created_at',
            'updated_at',
            'options',
        ]

        read_only_fields = ["id", "created_by", "created_at", "updated_at"]

    def update(self, instance, validated_data):
        return management.update_poll(
            self.context["request"].user, instance.pk, validated_data
        )


class OptionResultSerializer(serializers.ModelSerializer):
    votes = serializers.IntegerField()

    percentage = serializers.SerializerMethodField()

    class Meta:
        model = Option
        fields = ["id", "option_text", "votes", "percentage"]

    def get_percentage(self, obj):
        total = self.context.get("total_votes", 0)
        if total == 0:
            return 0
        return round((obj.votes / total) * 100, 2)


class PollResultsSerializer(serializers.ModelSerializer):
    options = OptionResultSerializer(many=True)
    total_votes = serializers.IntegerField()

    class Meta:
        model = Poll
        fields = [
            "id",
            "question",
            "description",
            "category",
            "created_by",
            "allow_multiple",
            "is_public",
            "expires_at",
            "created_at",
            "updated_at",
            "total_votes",
            "options",
        ]
