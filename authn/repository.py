from datetime import datetime

from django.utils import timezone

from authn.models import RefreshToken


class RefreshTokenRepository:
    async def create(self, user_id: str, token_hash: str, expires_at: datetime) -> RefreshToken:
        return await RefreshToken.objects.acreate(
            user_id=user_id, token_hash=token_hash, expires_at=expires_at
        )

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        return (
            await RefreshToken.objects.filter(token_hash=token_hash).select_related("user").afirst()
        )

    async def revoke(self, token: RefreshToken) -> None:
        token.revoked_at = timezone.now()
        await token.asave(update_fields=["revoked_at"])

    async def revoke_all_for_user(self, user_id: str) -> None:
        await RefreshToken.objects.filter(user_id=user_id, revoked_at__isnull=True).aupdate(
            revoked_at=timezone.now()
        )
