from collections.abc import Mapping

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers, generics, permissions
from .models import Poll, Option


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


class OptionCreateView(generics.CreateAPIView):
    serializer_class = OptionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        poll_id = self.kwargs["poll_id"]
        get_object_or_404(Poll, id=poll_id)
        serializer.save(poll_id=poll_id)


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
        options_data = validated_data.pop('options')
        poll = Poll.objects.create(**validated_data)

        # Create linked options
        for opt in options_data:
            Option.objects.create(poll=poll, **opt)

        return poll


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

    def validate(self, attrs):
        if (
            self.instance is not None
            and "allow_multiple" in attrs
            and attrs["allow_multiple"] != self.instance.allow_multiple
            and self.instance.votes.exists()
        ):
            raise serializers.ValidationError(
                {
                    "allow_multiple": "Voting mode cannot change with votes."
                }
            )
        return attrs


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
