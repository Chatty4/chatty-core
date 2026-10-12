from datetime import datetime

from django.utils import timezone

from authn.models import RefreshToken


class RefreshTokenRepository:
    async def create(self, user_id: str, token_hash: str, expires_at: datetime) -> RefreshToken:
        return await RefreshToken.objects.acreate(
            user_id=user_id, token_hash=token_hash, expires_at=expires_at
        )

    @staticmethod
    def create_sync(user_id: str, token_hash: str, expires_at: datetime) -> RefreshToken:
        return RefreshToken.objects.create(
            user_id=user_id, token_hash=token_hash, expires_at=expires_at
        )

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        return await RefreshToken.objects.filter(token_hash=token_hash).afirst()

    @staticmethod
    def get_by_hash_sync(token_hash: str) -> RefreshToken | None:
        return (
            RefreshToken.objects.select_for_update()
            .select_related("user")
            .filter(token_hash=token_hash)
            .first()
        )

    async def revoke(self, token: RefreshToken) -> None:
        token.revoked_at = timezone.now()
        await token.asave(update_fields=["revoked_at"])

    @staticmethod
    def revoke_sync(token: RefreshToken) -> None:
        token.revoked_at = timezone.now()
        token.save(update_fields=["revoked_at"])

    async def revoke_all_for_user(self, user_id: str, except_hash: str | None = None) -> None:
        tokens = RefreshToken.objects.filter(user_id=user_id, revoked_at__isnull=True)
        if except_hash:
            tokens = tokens.exclude(token_hash=except_hash)
        await tokens.aupdate(revoked_at=timezone.now())
