import hashlib
import secrets
import uuid
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

import jwt
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from authn.repository import RefreshTokenRepository
from authn.schemas import TokenPairSchema
from shared.codes import ErrorCode
from shared.exceptions import Unauthorized
from users.models import User


@lru_cache(maxsize=1)
def _private_key() -> str:
    return Path(settings.JWT_PRIVATE_KEY_PATH).read_text()


class AuthnService:
    def __init__(self) -> None:
        self.repo = RefreshTokenRepository()

    async def issue_tokens(self, user: User) -> TokenPairSchema:
        """Create a new access + refresh token pair for the given user."""
        raw, token_hash, expires_at = self._new_refresh_token()
        await self.repo.create(str(user.id), token_hash, expires_at)
        return self._build_token_pair(str(user.id), raw)

    async def refresh_tokens(self, raw_token: str) -> TokenPairSchema:
        """Rotate a refresh token: revoke the old one and issue a new pair. Raises Unauthorized if
        the token is missing, revoked, or expired."""
        token = await self.repo.get_by_hash(hashlib.sha256(raw_token.encode()).hexdigest())

        if token is None or token.revoked_at is not None or token.expires_at <= timezone.now():
            raise Unauthorized(ErrorCode.INVALID_REFRESH_TOKEN)

        new_raw, new_hash, new_expires_at = self._new_refresh_token()
        async with transaction.atomic():
            await self.repo.revoke(token)
            await self.repo.create(str(token.user_id), new_hash, new_expires_at)

        return self._build_token_pair(str(token.user_id), new_raw)

    async def revoke_refresh_token(self, raw_token: str) -> None:
        """Revoke a single refresh token. No-op if already revoked or not found."""
        token = await self.repo.get_by_hash(hashlib.sha256(raw_token.encode()).hexdigest())
        if token is None or token.revoked_at is not None:
            return
        await self.repo.revoke(token)

    async def revoke_all_tokens(self, user_id: str) -> None:
        """Revoke all active refresh tokens for a user (e.g. on logout from all devices)."""
        await self.repo.revoke_all_for_user(user_id)

    @staticmethod
    def _new_refresh_token() -> tuple[str, str, datetime]:
        raw = "rt_" + secrets.token_hex(32)
        expires_at = timezone.now() + timedelta(seconds=settings.JWT_REFRESH_TOKEN_LIFETIME)
        return raw, hashlib.sha256(raw.encode()).hexdigest(), expires_at

    def _build_token_pair(self, user_id: str, raw_refresh: str) -> TokenPairSchema:
        return TokenPairSchema(
            access_token=self._sign_access_token(user_id),
            token_type="Bearer",
            expires_in=settings.JWT_ACCESS_TOKEN_LIFETIME,
            refresh_token=raw_refresh,
            refresh_expires_in=settings.JWT_REFRESH_TOKEN_LIFETIME,
        )

    @staticmethod
    def _sign_access_token(user_id: str) -> str:
        now = timezone.now()
        return jwt.encode(
            {
                "sub": user_id,
                "iat": now,
                "exp": now + timedelta(seconds=settings.JWT_ACCESS_TOKEN_LIFETIME),
                "jti": str(uuid.uuid4()),
            },
            _private_key(),
            algorithm="RS256",
        )
