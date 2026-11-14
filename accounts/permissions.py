"""A shared fail-closed gate for both public registration APIs."""

from django.conf import settings
from rest_framework.exceptions import APIException
from rest_framework.permissions import BasePermission


class RegistrationUnavailable(APIException):
    status_code = 503
    default_detail = "Public registration is not available yet."
    default_code = "registration_disabled"


class RegistrationEnabled(BasePermission):
    def has_permission(self, request, view):
        if not getattr(settings, "NEXUS_REGISTRATION_ENABLED", False):
            raise RegistrationUnavailable()
        return True
