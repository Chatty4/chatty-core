from django.conf import settings
from django.http import HttpRequest
from rest_framework.request import Request


def client_ip(request: HttpRequest | Request) -> str:
    """The caller's IP. X-Real-IP is trusted only behind our Nginx, which overwrites it (D-09)."""
    if settings.BEHIND_PROXY:
        return request.headers.get("X-Real-IP") or request.META["REMOTE_ADDR"]
    return request.META["REMOTE_ADDR"]
