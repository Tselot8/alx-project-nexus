"""Existing routes retain SimpleJWT status codes and response shapes."""

from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)

from .jwt_serializers import (
    LegacyTokenObtainPairSerializer,
    LegacyTokenRefreshSerializer,
)


class LegacyTokenObtainPairView(TokenObtainPairView):
    serializer_class = LegacyTokenObtainPairSerializer


class LegacyTokenRefreshView(TokenRefreshView):
    serializer_class = LegacyTokenRefreshSerializer
