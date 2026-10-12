import hmac
import uuid
from typing import Any

from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.request import Request

from authn.services import AuthnService
from shared.codes import ErrorCode
from shared.exceptions import Unauthorized, UserInactive
from users.repositories import UserRepository


class JWTAuthentication(BaseAuthentication):
    """Bearer JWT for /api/core/v1. Sets request.user to the authenticated User."""

    def authenticate(self, request: Request) -> tuple[Any, Any] | None:
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return None

        payload = AuthnService.decode_access_token(header[7:])

        try:
            user_id = uuid.UUID(payload["sub"])
        except KeyError, ValueError:
            raise Unauthorized(ErrorCode.UNAUTHORIZED, "invalid token")

        user = UserRepository.get_by_id_sync(user_id)
        if user is None:
            raise Unauthorized(ErrorCode.UNAUTHORIZED, "user not found")
        if not user.is_active:
            raise UserInactive()

        return (user, payload)


class ServiceTokenAuthentication(BaseAuthentication):
    """X-Service-Token for /internal. The caller is chatty-chat, not the user."""

    def authenticate(self, request: Request) -> tuple[Any, Any] | None:
        token = request.headers.get("X-Service-Token", "")
        if not token or not hmac.compare_digest(
            token.encode(), settings.CORE_SERVICE_TOKEN.encode()
        ):
            raise Unauthorized(ErrorCode.INVALID_SERVICE_TOKEN, "missing or wrong X-Service-Token")
        return (None, None)
