import hmac
from typing import Any

from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.request import Request

from shared.codes import ErrorCode
from shared.exceptions import Unauthorized


class ServiceTokenAuthentication(BaseAuthentication):
    """X-Service-Token for /internal. The caller is chatty-chat, not the user."""

    def authenticate(self, request: Request) -> tuple[Any, Any] | None:
        token = request.headers.get("X-Service-Token", "")
        if not token or not hmac.compare_digest(
            token.encode(), settings.CORE_SERVICE_TOKEN.encode()
        ):
            raise Unauthorized(ErrorCode.INVALID_SERVICE_TOKEN, "missing or wrong X-Service-Token")
        return (None, None)
