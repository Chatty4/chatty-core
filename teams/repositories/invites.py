from datetime import timedelta
from uuid import UUID

from django.db.models import F, Q, QuerySet
from django.utils import timezone

from teams.models import Invite, Team


class InviteRepository:
    @staticmethod
    async def get_by_id(invite_id: UUID) -> Invite | None:
        """Return an invite by id, or None if not found or its team is deleted."""
        return await Invite.objects.filter(id=invite_id, team__deleted_at__isnull=True).afirst()

    @staticmethod
    async def get_by_code(code: str) -> Invite | None:
        """
        Return an invite by code with its team loaded, or None if
        not found or team is deleted.
        """
        return await (
            Invite.objects.select_related("team")
            .filter(code=code, team__deleted_at__isnull=True)
            .afirst()
        )

    @staticmethod
    def code_exists_sync(code: str) -> bool:
        """Check whether an invite with this code already exists."""
        return Invite.objects.filter(code=code).exists()

    @staticmethod
    async def list_active(team_id: UUID, created_by_id: UUID | None = None) -> list[Invite]:
        """Active invites for the team. Pass created_by_id to restrict to one user's invites."""
        qs = InviteRepository._active_qs(team_id).order_by("created_at")
        if created_by_id is not None:
            qs = qs.filter(created_by_id=created_by_id)
        return [invite async for invite in qs]

    @staticmethod
    def count_active_sync(team_id: UUID) -> int:
        """Count active invites for the team. Locks the team row so a concurrent create
        can't race past the 100-invite cap check."""
        Team.objects.select_for_update().get(id=team_id)
        return InviteRepository._active_qs(team_id).count()

    @staticmethod
    def _active_qs(team_id: UUID) -> QuerySet[Invite]:
        """Base queryset for active invites: not revoked, not expired, not used up."""
        now = timezone.now()
        return (
            Invite.objects.filter(team_id=team_id)
            .filter(revoked_at__isnull=True)
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
            .filter(Q(max_uses=0) | Q(uses__lt=F("max_uses")))
        )

    @staticmethod
    def create_sync(team_id: UUID, user_id: UUID, code: str, max_age: int, max_uses: int) -> Invite:
        """Insert and return a new invite. Computes expires_at from max_age (null when 0)."""
        expires_at = timezone.now() + timedelta(seconds=max_age) if max_age else None
        return Invite.objects.create(
            team_id=team_id,
            created_by_id=user_id,
            code=code,
            max_uses=max_uses,
            expires_at=expires_at,
        )

    @staticmethod
    def increment_uses_sync(invite: Invite) -> None:
        """Add 1 to uses. Call only with row locked."""
        invite.uses += 1
        invite.save(update_fields=["uses"])

    @staticmethod
    async def revoke(invite: Invite) -> None:
        """Set revoked_at to now."""
        invite.revoked_at = timezone.now()
        await invite.asave(update_fields=["revoked_at"])

    @staticmethod
    def revoke_created_by_sync(team_id: UUID, user_id: UUID) -> None:
        """Revoke every invite this user created for the team that isn't revoked yet."""
        Invite.objects.filter(
            team_id=team_id, created_by_id=user_id, revoked_at__isnull=True
        ).update(revoked_at=timezone.now())

    @staticmethod
    async def revoke_all_created_by(user_id: UUID) -> None:
        """Revoke every invite this user created, in any team, that isn't revoked yet."""
        await Invite.objects.filter(created_by_id=user_id, revoked_at__isnull=True).aupdate(
            revoked_at=timezone.now()
        )

    @staticmethod
    def lock_by_id_sync(invite_id: UUID) -> Invite:
        """Lock the invite row until the transaction ends, and return it."""
        return Invite.objects.select_for_update().get(id=invite_id)
