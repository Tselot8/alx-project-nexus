"""Versioned legacy JWT hooks preserving the existing JSON contracts."""

from uuid import UUID

from django.contrib.auth import get_user_model
from django.db import transaction
from django.views.decorators.debug import sensitive_variables
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import (
    TokenObtainPairSerializer,
    TokenRefreshSerializer,
)

from .authentication import VersionedRefreshToken, check_auth_version


class LegacyTokenObtainPairSerializer(TokenObtainPairSerializer):
    token_class = VersionedRefreshToken

    @sensitive_variables()
    def validate(self, attrs):
        with transaction.atomic():
            # Authenticate while holding the same lock used by revocation.
            get_user_model().objects.select_for_update().filter(
                **{self.username_field: attrs[self.username_field]}
            ).first()
            return super().validate(attrs)


class LegacyTokenRefreshSerializer(TokenRefreshSerializer):
    token_class = VersionedRefreshToken

    @sensitive_variables()
    def validate(self, attrs):
        User = get_user_model()
        try:
            parsed = self.token_class(attrs["refresh"])
            user_id = UUID(str(parsed["user_id"]))
            with transaction.atomic():
                user = User.objects.select_for_update().get(pk=user_id)
                parsed = self.token_class(attrs["refresh"])
                if not user.is_active:
                    raise AuthenticationFailed(
                        self.error_messages["no_active_account"],
                        "no_active_account",
                    )
                try:
                    check_auth_version(parsed, user)
                except AuthenticationFailed:
                    raise InvalidToken(
                        "Invalid or revoked refresh token."
                    ) from None
                # Parent handles the configured legacy response/rotation.
                return super().validate(attrs)
        except (
            TokenError,
            User.DoesNotExist,
            KeyError,
            ValueError,
            TypeError,
        ):
            raise InvalidToken("Invalid or revoked refresh token.") from None
