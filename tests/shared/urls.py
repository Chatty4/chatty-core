"""Routes used only by tests/shared/test_views.py (selected with pytest.mark.urls)."""

from django.urls import path
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from shared.codes import ErrorCode
from shared.exceptions import NotFound
from shared.views import AsyncAPIView


class Ok(AsyncAPIView):
    async def get(self, request):
        return Response({"ok": True})


class Missing(AsyncAPIView):
    async def get(self, request):
        raise NotFound(ErrorCode.TEAM_NOT_FOUND)


class Crash(AsyncAPIView):
    async def get(self, request):
        raise RuntimeError("secret detail")


class Deny(BasePermission):
    def has_permission(self, request, view):
        return False


class Forbidden(AsyncAPIView):
    permission_classes = [Deny]

    async def get(self, request):
        return Response({"ok": True})


urlpatterns = [
    path("ok", Ok.as_view()),
    path("missing", Missing.as_view()),
    path("crash", Crash.as_view()),
    path("forbidden", Forbidden.as_view()),
]
