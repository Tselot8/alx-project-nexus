"""Explicit v2 poll contracts; no vote counts or voter identities."""

from rest_framework import serializers

from accounts.v2_serializers import StrictInput
from .models import Category, Poll
from .policy import configuration_is_locked, effective_status
from .services import is_poll_owner


class OptionInput(StrictInput, serializers.Serializer):
    option_text = serializers.CharField(
        max_length=255, allow_blank=True, trim_whitespace=True
    )


class PollInput(StrictInput, serializers.Serializer):
    question = serializers.CharField(
        required=False, allow_blank=True, max_length=2000
    )
    description = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, max_length=10000
    )
    category = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.all(), required=False, allow_null=True
    )
    visibility = serializers.ChoiceField(
        choices=["public", "private"], required=False
    )
    voting_mode = serializers.ChoiceField(
        choices=["single", "multiple"], required=False
    )
    results_visibility = serializers.ChoiceField(
        choices=Poll.ResultsVisibility.choices, required=False
    )
    min_selections = serializers.IntegerField(
        min_value=1, max_value=100, required=False
    )
    max_selections = serializers.IntegerField(
        min_value=1, max_value=100, allow_null=True, required=False
    )
    expires_at = serializers.DateTimeField(allow_null=True, required=False)

    def validate(self, attrs):
        if "visibility" in attrs:
            attrs["is_public"] = attrs.pop("visibility") == "public"
        if "voting_mode" in attrs:
            attrs["allow_multiple"] = attrs.pop("voting_mode") == "multiple"
        return attrs


class PollCreateInput(PollInput):
    options = OptionInput(many=True, required=False, max_length=100)


class ReopenInput(StrictInput, serializers.Serializer):
    expires_at = serializers.DateTimeField(allow_null=True)


class EmptyInput(StrictInput, serializers.Serializer):
    pass


class ShareInput(StrictInput, serializers.Serializer):
    token = serializers.RegexField(
        regex=r"\A[A-Za-z0-9_-]{43}\Z",
        max_length=43,
        min_length=43,
        write_only=True,
    )


class PagingInput(StrictInput, serializers.Serializer):
    page = serializers.IntegerField(min_value=1, required=False)
    page_size = serializers.IntegerField(
        min_value=1, max_value=100, required=False
    )


class DiscoveryInput(PagingInput):
    q = serializers.CharField(required=False, allow_blank=True, max_length=200)
    category = serializers.UUIDField(required=False)
    status = serializers.ChoiceField(
        choices=["published", "closed"], required=False
    )
    sort = serializers.ChoiceField(
        choices=["newest", "oldest", "closing_soon"], required=False
    )


class MyPollsInput(DiscoveryInput):
    status = serializers.ChoiceField(
        choices=Poll.Status.choices, required=False
    )


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name", "description"]
        read_only_fields = fields


class PollSummary(serializers.ModelSerializer):
    status = serializers.SerializerMethodField()
    visibility = serializers.SerializerMethodField()
    voting_mode = serializers.SerializerMethodField()

    class Meta:
        model = Poll
        fields = [
            "id",
            "question",
            "description",
            "category",
            "created_by",
            "visibility",
            "voting_mode",
            "status",
            "expires_at",
            "created_at",
            "version",
        ]
        read_only_fields = fields

    def to_representation(self, poll):
        data = super().to_representation(poll)
        request = self.context.get("request")
        user = request.user if request else None
        if not is_poll_owner(user, poll):
            for name in (
                "version",
                "configuration_locked",
                "configuration_editable",
                "updated_at",
            ):
                data.pop(name, None)
        return data

    def get_status(self, poll):
        return effective_status(poll)

    def get_visibility(self, poll):
        return "public" if poll.is_public else "private"

    def get_voting_mode(self, poll):
        return "multiple" if poll.allow_multiple else "single"


class PollDetail(PollSummary):
    options = serializers.SerializerMethodField()
    configuration_editable = serializers.SerializerMethodField()

    class Meta(PollSummary.Meta):
        fields = PollSummary.Meta.fields + [
            "results_visibility",
            "min_selections",
            "max_selections",
            "configuration_locked",
            "configuration_editable",
            "updated_at",
            "options",
        ]
        read_only_fields = fields

    def get_options(self, poll):
        return [
            {"id": str(option.pk), "option_text": option.option_text}
            for option in poll.options.order_by("id")
        ]

    def get_configuration_editable(self, poll):
        request = self.context.get("request")
        if not request or not is_poll_owner(request.user, poll):
            return None
        return (
            poll.status != Poll.Status.ARCHIVED
            and not configuration_is_locked(poll)
        )
