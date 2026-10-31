"""Frontend-facing JWT APIs with explicit anonymous CSRF enforcement."""

from django.conf import settings
from django.db import IntegrityError, transaction
from django.middleware.csrf import CsrfViewMiddleware, get_token, rotate_token
from django.utils.decorators import method_decorator
from django.views.decorators.debug import sensitive_post_parameters
from rest_framework import permissions, status
from rest_framework.exceptions import APIException, PermissionDenied
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from . import v2_services as services
from .v2_serializers import (
    AccountUpdateSerializer,
    LoginSerializer,
    PasswordChangeSerializer,
    RegistrationSerializer,
    ResetConfirmSerializer,
    ResetRequestSerializer,
    account_data,
)


class RecoveryUnavailable(APIException):
    status_code = 503
    default_detail = "Password recovery is not available yet."
    default_code = "recovery_unavailable"


class ConnectionAddressThrottle(ScopedRateThrottle):
    def get_ident(self, request):
        # Do not trust caller-supplied forwarding headers.
        return request.META.get("REMOTE_ADDR", "")


@method_decorator(sensitive_post_parameters(), name="dispatch")
class V2View(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [ConnectionAddressThrottle]
    throttle_scope = "v2_account"
    csrf_required = False

    def initial(self, request, *args, **kwargs):
        if self.csrf_required:
            original = request._request
            middleware = CsrfViewMiddleware(lambda req: None)
            middleware.process_request(original)
            if (
                middleware.process_view(original, lambda req: None, (), {})
                is not None
            ):
                raise PermissionDenied("CSRF verification failed.")
        super().initial(request, *args, **kwargs)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(
            request, response, *args, **kwargs
        )
        response["Cache-Control"] = "private, no-store"
        response["Pragma"] = "no-cache"
        response["Referrer-Policy"] = "no-referrer"
        return response

    def get_authenticate_header(self, request):
        return 'Bearer realm="api"'

    def handle_exception(self, exc):
        response = super().handle_exception(exc)
        response.data = {
            "error": {
                "code": getattr(exc, "default_code", "request_failed"),
                "details": response.data,
            }
        }
        return response


class AnonymousCookieView(V2View):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    csrf_required = True
    throttle_scope = "v2_auth"


def cookie_options():
    return {
        "path": "/api/v2/auth/",
        "secure": settings.NEXUS_REFRESH_COOKIE_SECURE,
        "httponly": True,
        "samesite": "Lax",
    }


def session_response(request, user, refresh, code=200):
    rotate_token(request._request)
    access = refresh.access_token
    response = Response(
        {
            "user": account_data(user),
            "access": str(access),
            "expires_in": access["exp"] - access["iat"],
            "csrf_token": get_token(request._request),
        },
        status=code,
    )
    response.set_cookie(
        "nexus_v2_refresh_token",
        str(refresh),
        max_age=int(refresh.lifetime.total_seconds()),
        **cookie_options(),
    )
    return response


def cleared_response():
    response = Response(status=status.HTTP_204_NO_CONTENT)
    response.set_cookie(
        "nexus_v2_refresh_token",
        "",
        max_age=0,
        expires="Thu, 01 Jan 1970 00:00:00 GMT",
        **cookie_options(),
    )
    return response


class CsrfView(V2View):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response({"csrf_token": get_token(request._request)})


class RegistrationView(AnonymousCookieView):
    def post(self, request):
        serializer = RegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                user = serializer.save()
                refresh = services.CookieRefreshToken.for_user(user)
        except IntegrityError:
            from rest_framework.exceptions import ValidationError

            raise ValidationError(
                {"account": ["Email or username is unavailable."]}
            ) from None
        return session_response(request, user, refresh, code=201)


class LoginView(AnonymousCookieView):
    throttle_scope = "v2_login"

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user, refresh = services.login(
            request._request, **serializer.validated_data
        )
        return session_response(request, user, refresh)


class RefreshView(AnonymousCookieView):
    def post(self, request):
        user, refresh = services.refresh_session(
            request.COOKIES.get("nexus_v2_refresh_token", "")
        )
        # Keep CSRF stable during refresh so concurrent tabs can recover.
        access = refresh.access_token
        response = Response(
            {
                "access": str(access),
                "expires_in": access["exp"] - access["iat"],
            }
        )
        response.set_cookie(
            "nexus_v2_refresh_token",
            str(refresh),
            max_age=int(refresh.lifetime.total_seconds()),
            **cookie_options(),
        )
        return response


class LogoutView(AnonymousCookieView):
    def post(self, request):
        services.refresh_session(
            request.COOKIES.get("nexus_v2_refresh_token", ""), rotate=False
        )
        return cleared_response()


class LogoutAllView(V2View):
    csrf_required = True

    def post(self, request):
        services.logout_all(request.user)
        return cleared_response()


class MeView(V2View):
    def get(self, request):
        return Response({"user": account_data(request.user)})

    def patch(self, request):
        serializer = AccountUpdateSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        user = services.update_account(request.user, serializer.validated_data)
        return Response({"user": account_data(user)})


class PasswordChangeView(V2View):
    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.change_password(request.user, **serializer.validated_data)
        return cleared_response()


class ResetRequestView(AnonymousCookieView):
    throttle_scope = "v2_recovery"

    def post(self, request):
        if not settings.NEXUS_PASSWORD_RESET_ENABLED:
            raise RecoveryUnavailable()
        serializer = ResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.request_password_reset(**serializer.validated_data)
        return Response(
            {
                "message": "If the account is eligible, password reset "
                "instructions will be sent."
            },
            status=202,
        )


class ResetConfirmView(AnonymousCookieView):
    throttle_scope = "v2_recovery"

    def post(self, request):
        if not settings.NEXUS_PASSWORD_RESET_ENABLED:
            raise RecoveryUnavailable()
        serializer = ResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.confirm_password_reset(**serializer.validated_data)
        return cleared_response()
