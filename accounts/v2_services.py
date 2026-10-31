"""V2 cookie sessions. All session mutations lock the user before tokens."""

from datetime import timedelta
from smtplib import SMTPException
from urllib.parse import urlencode
from uuid import UUID

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views.decorators.debug import sensitive_variables
from rest_framework.exceptions import AuthenticationFailed, ValidationError
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)

from .authentication import VersionedRefreshToken, check_auth_version
from .models import UserProfile
from .v2_serializers import validate_new_password

User = get_user_model()
INVALID_SESSION = "Invalid or expired refresh session."


class CookieRefreshToken(VersionedRefreshToken):
    # Legacy refresh rejects this type even if copied into a JSON body.
    token_type = "nexus_v2_refresh_token"
    lifetime = timedelta(days=7)


class RecoveryTokenGenerator(PasswordResetTokenGenerator):
    key_salt = "accounts.v2.password_recovery"


recovery_tokens = RecoveryTokenGenerator()


@sensitive_variables()
def login(request, email, password):
    user = authenticate(request=request, email=email, password=password)
    if user is None:
        raise AuthenticationFailed("Invalid email or password.")
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user.pk)
        # Recheck after locking, against concurrent password/status changes.
        if not user.is_active or not user.check_password(password):
            raise AuthenticationFailed("Invalid email or password.")
        return user, CookieRefreshToken.for_user(user)


@sensitive_variables()
def refresh_session(raw, rotate=True):
    try:
        parsed = CookieRefreshToken(raw)
        user_id = UUID(str(parsed["user_id"]))
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=user_id)
            if not user.is_active:
                raise AuthenticationFailed(INVALID_SESSION)
            # A competing refresh may have revoked it while we waited.
            parsed = CookieRefreshToken(raw)
            check_auth_version(parsed, user)
            outstanding = OutstandingToken.objects.get(
                jti=parsed["jti"], user=user
            )
            BlacklistedToken.objects.create(token=outstanding)
            replacement = CookieRefreshToken.for_user(user) if rotate else None
            return user, replacement
    except (
        TokenError,
        KeyError,
        TypeError,
        ValueError,
        User.DoesNotExist,
        OutstandingToken.DoesNotExist,
        IntegrityError,
    ):
        raise AuthenticationFailed(INVALID_SESSION) from None


def revoke_sessions(user):
    # The row lock serializes this increment with BOTH refresh implementations.
    # Also revokes pre-tracking tokens that have no OutstandingToken record.
    user.auth_version += 1
    user.save(update_fields=["auth_version"])
    # Blacklisting remains useful for per-session revocation/replay checks.
    BlacklistedToken.objects.bulk_create(
        [
            BlacklistedToken(token_id=pk)
            for pk in OutstandingToken.objects.filter(user=user).values_list(
                "pk", flat=True
            )
        ],
        ignore_conflicts=True,
    )


def logout_all(user):
    with transaction.atomic():
        locked = User.objects.select_for_update().get(pk=user.pk)
        revoke_sessions(locked)


@sensitive_variables()
def change_password(user, current_password, new_password):
    with transaction.atomic():
        locked = User.objects.select_for_update().get(pk=user.pk)
        if not locked.check_password(current_password):
            raise ValidationError(
                {"current_password": ["The current password is incorrect."]}
            )
        validate_new_password(new_password, locked)
        locked.set_password(new_password)
        locked.save(update_fields=["password"])
        revoke_sessions(locked)


def update_account(user, data):
    with transaction.atomic():
        locked = User.objects.select_for_update().get(pk=user.pk)
        if "username" in data:
            locked.username = data["username"]
            try:
                with transaction.atomic():
                    locked.save(update_fields=["username"])
            except IntegrityError:
                raise ValidationError(
                    {"username": ["This username is unavailable."]}
                ) from None
        if "profile" in data:
            profile, _ = UserProfile.objects.get_or_create(user=locked)
            for field, value in data["profile"].items():
                setattr(profile, field, value)
            profile.save()
        return locked


@sensitive_variables()
def request_password_reset(email):
    # Never log recipient existence, tokens, or delivery error details.
    for user in User.objects.filter(email=email, is_active=True):
        if not user.has_usable_password():
            continue
        query = urlencode(
            {
                "uid": urlsafe_base64_encode(force_bytes(user.pk)),
                "token": recovery_tokens.make_token(user),
            }
        )
        link = (
            settings.NEXUS_PASSWORD_RESET_ORIGIN + "/reset-password#" + query
        )
        try:
            send_mail(
                "Reset your Project Nexus password",
                "Use this link to reset your password. It expires in "
                "30 minutes. If you did not request this, ignore it.\n\n"
                + link,
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
                fail_silently=False,
            )
        except (SMTPException, OSError):
            # Delivery monitoring must not log message contents or exceptions.
            pass


@sensitive_variables()
def confirm_password_reset(uid, token, new_password):
    try:
        user_id = UUID(urlsafe_base64_decode(uid).decode())
    except (ValueError, TypeError, UnicodeError, OverflowError):
        raise ValidationError({"token": ["Invalid or expired reset link."]})
    with transaction.atomic():
        user = User.objects.select_for_update().filter(pk=user_id).first()
        if (
            user is None
            or not user.is_active
            or not user.has_usable_password()
            or not recovery_tokens.check_token(user, token)
        ):
            raise ValidationError(
                {"token": ["Invalid or expired reset link."]}
            )
        validate_new_password(new_password, user)
        user.set_password(new_password)
        user.save(update_fields=["password"])
        revoke_sessions(user)
