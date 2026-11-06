from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from rest_framework import generics, permissions

from .v2_views import ConnectionAddressThrottle
from .serializers import RegisterSerializer


@method_decorator(never_cache, name="dispatch")
class RegisterView(generics.CreateAPIView):
    throttle_classes = [ConnectionAddressThrottle]
    throttle_scope = "v2_auth"
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]
