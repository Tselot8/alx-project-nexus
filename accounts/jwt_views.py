"""Existing routes retain SimpleJWT status codes and response shapes."""

from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache

from .v2_views import ConnectionAddressThrottle
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)

from .jwt_serializers import (
    LegacyTokenObtainPairSerializer,
    LegacyTokenRefreshSerializer,
)


@method_decorator(never_cache, name="dispatch")
class LegacyTokenObtainPairView(TokenObtainPairView):
    throttle_classes = [ConnectionAddressThrottle]
    throttle_scope = "v2_login"
    serializer_class = LegacyTokenObtainPairSerializer


@method_decorator(never_cache, name="dispatch")
class LegacyTokenRefreshView(TokenRefreshView):
    throttle_classes = [ConnectionAddressThrottle]
    throttle_scope = "v2_auth"
    serializer_class = LegacyTokenRefreshSerializer
