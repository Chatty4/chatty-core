from datetime import datetime

from django.db.models import Q
from django.utils import timezone

from authn.models import RefreshToken


class RefreshTokenRepository:
    @staticmethod
    async def create(user_id: str, token_hash: str, expires_at: datetime) -> RefreshToken:
        return await RefreshToken.objects.acreate(
            user_id=user_id, token_hash=token_hash, expires_at=expires_at
        )

    @staticmethod
    def create_sync(user_id: str, token_hash: str, expires_at: datetime) -> RefreshToken:
        return RefreshToken.objects.create(
            user_id=user_id, token_hash=token_hash, expires_at=expires_at
        )

    @staticmethod
    async def get_by_hash(token_hash: str) -> RefreshToken | None:
        return await RefreshToken.objects.filter(token_hash=token_hash).afirst()

    @staticmethod
    def get_by_hash_sync(token_hash: str) -> RefreshToken | None:
        return (
            RefreshToken.objects.select_for_update(of=("self",))
            .select_related("user")
            .filter(token_hash=token_hash)
            .first()
        )

    @staticmethod
    def revoke_sync(token: RefreshToken) -> None:
        """Mark the token as rotated. Only rotation sets revoked_at, so a later reuse is theft."""
        token.revoked_at = timezone.now()
        token.save(update_fields=["revoked_at"])

    @staticmethod
    async def delete(token: RefreshToken) -> None:
        await token.adelete()

    @staticmethod
    async def delete_all_for_user(user_id: str, except_hash: str | None = None) -> None:
        """Delete every refresh token of the user, rotated ones included, except except_hash."""
        tokens = RefreshToken.objects.filter(user_id=user_id)
        if except_hash:
            tokens = tokens.exclude(token_hash=except_hash)
        await tokens.adelete()

    @staticmethod
    def delete_all_for_user_sync(user_id: str, except_hash: str | None = None) -> None:
        tokens = RefreshToken.objects.filter(user_id=user_id)
        if except_hash:
            tokens = tokens.exclude(token_hash=except_hash)
        tokens.delete()

    @staticmethod
    def _stale_qs(cutoff: datetime):
        return RefreshToken.objects.filter(Q(expires_at__lt=cutoff) | Q(revoked_at__lt=cutoff))

    @staticmethod
    def count_old(cutoff: datetime) -> int:
        return RefreshTokenRepository._stale_qs(cutoff).count()

    @staticmethod
    def purge_old(cutoff: datetime) -> int:
        """Delete tokens that expired or were revoked before cutoff. Returns count deleted."""
        count, _ = RefreshTokenRepository._stale_qs(cutoff).delete()
        return count
