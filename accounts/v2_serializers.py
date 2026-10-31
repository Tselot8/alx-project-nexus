"""Explicit v2 input/output allowlists; legacy serializers are unchanged."""

from collections.abc import Mapping

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .serializers import RegisterSerializer

User = get_user_model()


class StrictInput:
    def to_internal_value(self, data):
        if not isinstance(data, Mapping):
            return super().to_internal_value(data)
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {
                    field: ["This field cannot be supplied."]
                    for field in sorted(unknown)
                }
            )
        return super().to_internal_value(data)


class RegistrationSerializer(StrictInput, RegisterSerializer):
    pass


class LoginSerializer(StrictInput, serializers.Serializer):
    email = serializers.EmailField(max_length=100)
    password = serializers.CharField(
        trim_whitespace=False, write_only=True, max_length=1024
    )


class ProfileSerializer(StrictInput, serializers.Serializer):
    bio = serializers.CharField(
        max_length=2000, allow_blank=True, allow_null=True, required=False
    )
    location = serializers.CharField(
        max_length=100, allow_blank=True, allow_null=True, required=False
    )


class AccountUpdateSerializer(StrictInput, serializers.Serializer):
    username = serializers.CharField(max_length=50, required=False)
    profile = ProfileSerializer(required=False)

    def validate_username(self, value):
        user = self.context["request"].user
        if User.objects.exclude(pk=user.pk).filter(username=value).exists():
            raise serializers.ValidationError("This username is unavailable.")
        return value


def validate_new_password(password, user):
    try:
        validate_password(password, user=user)
    except DjangoValidationError as error:
        raise serializers.ValidationError(
            {"new_password": error.messages}
        ) from error


class PasswordChangeSerializer(StrictInput, serializers.Serializer):
    current_password = serializers.CharField(
        trim_whitespace=False, write_only=True, max_length=1024
    )
    new_password = serializers.CharField(
        trim_whitespace=False, write_only=True, max_length=1024
    )


class ResetRequestSerializer(StrictInput, serializers.Serializer):
    email = serializers.EmailField(max_length=100)


class ResetConfirmSerializer(StrictInput, serializers.Serializer):
    uid = serializers.CharField(max_length=64)
    token = serializers.CharField(max_length=128, trim_whitespace=False)
    new_password = serializers.CharField(
        trim_whitespace=False, write_only=True, max_length=1024
    )


def account_data(user):
    """Private current-user fields only, with a read-only email identity."""
    profile = getattr(user, "profile", None)
    return {
        "id": str(user.pk),
        "username": user.username,
        "email": user.email,
        "profile": {
            "bio": profile.bio if profile else None,
            "location": profile.location if profile else None,
        },
    }
