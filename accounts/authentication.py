"""One version check shared by legacy and v2 JWT authentication."""

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)
from rest_framework_simplejwt.tokens import RefreshToken, Token
from rest_framework_simplejwt.utils import datetime_from_epoch


def check_auth_version(token, user):
    # Versionless tokens work only until the first revocation.
    version = token.get("auth_version", 1)
    if (
        not user.is_active
        or type(version) is not int
        or version != user.auth_version
    ):
        raise AuthenticationFailed("Invalid or revoked session.")


class VersionedJWTAuthentication(JWTAuthentication):
    def get_user(self, validated_token):
        try:
            user = super().get_user(validated_token)
        except (DjangoValidationError, ValueError, TypeError):
            raise AuthenticationFailed("Invalid session.") from None
        check_auth_version(validated_token, user)
        return user


class VersionedRefreshToken(RefreshToken):
    @classmethod
    def for_user(cls, user):
        # Application issuers hold the user row lock and use its current state.
        if not user.is_active:
            raise AuthenticationFailed("Inactive account.")
        # Store the JTI without persisting the signed refresh JWT.
        token = Token.for_user.__func__(cls, user)
        token["auth_version"] = user.auth_version
        OutstandingToken.objects.create(
            user=user,
            jti=token["jti"],
            token="",
            created_at=token.current_time,
            expires_at=datetime_from_epoch(token["exp"]),
        )
        return token

    def outstand(self):
        record, _ = OutstandingToken.objects.get_or_create(
            jti=self["jti"],
            defaults={
                "user_id": self["user_id"],
                "token": "",
                "created_at": self.current_time,
                "expires_at": datetime_from_epoch(self["exp"]),
            },
        )
        return record

    def blacklist(self):
        return BlacklistedToken.objects.get_or_create(token=self.outstand())
