import hashlib
import secrets
import uuid
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

import jwt
from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from authn.repositories import RefreshTokenRepository
from authn.schemas import TokenPairSchema
from shared.codes import ErrorCode
from shared.exceptions import PermissionDenied, Unauthorized, UserInactive
from users.models import User


@lru_cache(maxsize=1)
def _private_key() -> str:
    return Path(settings.JWT_PRIVATE_KEY_PATH).read_text()


@lru_cache(maxsize=1)
def _public_key() -> str:
    return Path(settings.JWT_PUBLIC_KEY_PATH).read_text()


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class AuthnService:
    @staticmethod
    def decode_access_token(token: str) -> dict:
        """Decode and verify an RS256 access token. Raises Unauthorized on failure."""
        try:
            return jwt.decode(
                token, _public_key(), algorithms=["RS256"], options={"require": ["exp", "sub"]}
            )
        except jwt.ExpiredSignatureError:
            raise Unauthorized(ErrorCode.UNAUTHORIZED, "token expired")
        except jwt.InvalidTokenError:
            raise Unauthorized(ErrorCode.UNAUTHORIZED, "invalid token")

    async def check_own_refresh_token(self, raw_token: str, user_id: str) -> None:
        """Raise unless raw_token is a live refresh token owned by user_id."""
        token = await RefreshTokenRepository.get_by_hash(_hash_token(raw_token))
        if token is None:
            raise Unauthorized(ErrorCode.INVALID_REFRESH_TOKEN)
        if str(token.user_id) != user_id:
            raise PermissionDenied(ErrorCode.FORBIDDEN)
        if token.revoked_at is not None or token.expires_at <= timezone.now():
            raise Unauthorized(ErrorCode.INVALID_REFRESH_TOKEN)

    async def issue_tokens(self, user: User) -> TokenPairSchema:
        """Create a new access + refresh token pair for the given user."""
        raw, token_hash, expires_at = self._new_refresh_token()
        await RefreshTokenRepository.create(str(user.id), token_hash, expires_at)
        return self._build_token_pair(str(user.id), raw)

    @staticmethod
    def _new_refresh_token() -> tuple[str, str, datetime]:
        raw = "rt_" + secrets.token_hex(32)
        expires_at = timezone.now() + timedelta(seconds=settings.JWT_REFRESH_TOKEN_LIFETIME)
        return raw, _hash_token(raw), expires_at

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

    async def refresh_tokens(self, raw_token: str) -> TokenPairSchema:
        """Rotate a refresh token: mark the old one as rotated and issue a new pair. Reusing a
        rotated token deletes every refresh token of the user."""
        new_raw, new_hash, new_expires_at = self._new_refresh_token()

        token_hash = _hash_token(raw_token)
        user_id, reuse = await sync_to_async(self._rotate_sync)(
            token_hash, new_hash, new_expires_at
        )

        if reuse:
            await RefreshTokenRepository.delete_all_for_user(user_id)
            raise Unauthorized(ErrorCode.INVALID_REFRESH_TOKEN)

        return self._build_token_pair(user_id, new_raw)

    @transaction.atomic
    def _rotate_sync(
        self, token_hash: str, new_hash: str, new_expires_at: datetime
    ) -> tuple[str, bool]:
        """Returns (user_id, reuse_detected). Reuse means the token was already rotated;
        the caller must revoke all sessions outside this transaction."""
        token = RefreshTokenRepository.get_by_hash_sync(token_hash)
        if token is None:
            raise Unauthorized(ErrorCode.INVALID_REFRESH_TOKEN)
        if token.revoked_at is not None:
            return str(token.user_id), True
        if token.expires_at <= timezone.now():
            raise Unauthorized(ErrorCode.INVALID_REFRESH_TOKEN)

        if not token.user.is_active:
            raise UserInactive()

        RefreshTokenRepository.revoke_sync(token)
        RefreshTokenRepository.create_sync(str(token.user_id), new_hash, new_expires_at)

        return str(token.user_id), False

    async def revoke_refresh_token(self, raw_token: str, user_id: str) -> None:
        """Log out one device by deleting its refresh token.
        Raises PermissionDenied if the token belongs to a different user.
        No-op if unknown or already rotated (contract).
        """
        token = await RefreshTokenRepository.get_by_hash(_hash_token(raw_token))
        if token is None:
            return
        if str(token.user_id) != user_id:
            raise PermissionDenied(ErrorCode.FORBIDDEN)
        if token.revoked_at is not None:
            return
        await RefreshTokenRepository.delete(token)

    async def revoke_all_tokens(self, user_id: str, keep_raw_token: str | None = None) -> None:
        """Delete all refresh tokens of a user, except keep_raw_token (this device)."""
        keep_hash = _hash_token(keep_raw_token) if keep_raw_token else None
        await RefreshTokenRepository.delete_all_for_user(user_id, except_hash=keep_hash)

    def revoke_all_tokens_sync(self, user_id: str, keep_raw_token: str) -> None:
        """revoke_all_tokens for use inside the caller's transaction.atomic."""
        RefreshTokenRepository.delete_all_for_user_sync(
            user_id, except_hash=_hash_token(keep_raw_token)
        )
