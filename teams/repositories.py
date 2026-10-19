from datetime import timedelta
from uuid import UUID

from django.contrib.auth import get_user_model
from django.db.models import Count, F, IntegerField, OuterRef, Q, QuerySet, Subquery
from django.utils import timezone

from shared.pagination import paginate
from teams.models import Invite, Team, TeamMember


class TeamRepository:
    @staticmethod
    async def get_by_id(team_id: UUID) -> Team | None:
        """Return a non-deleted team by id, or None."""
        return await Team.objects.filter(id=team_id, deleted_at__isnull=True).afirst()

    @staticmethod
    def count_created_by_sync(user_id: UUID) -> int:
        """Count non-deleted teams created by this user. Locks the user row until the
        transaction ends, so two parallel creates can't both pass the 10-team check."""
        # no_key: other inserts that reference this user (logins, joins) don't wait
        get_user_model().objects.select_for_update(no_key=True).get(id=user_id)
        return Team.objects.filter(created_by_id=user_id, deleted_at__isnull=True).count()

    @staticmethod
    def create_sync(name: str, created_by_id: UUID) -> Team:
        """Create and return a new team."""
        return Team.objects.create(name=name, created_by_id=created_by_id)

    @staticmethod
    async def list_by_user(user_id: UUID) -> list[Team]:
        """Return all non-deleted teams the user is a member of, annotated
        with their role and member count."""
        queryset = (
            Team.objects.filter(members__user_id=user_id, deleted_at__isnull=True)
            .annotate(
                role=Subquery(
                    TeamMember.objects.filter(team_id=OuterRef("pk"), user_id=user_id).values(
                        "role"
                    )[:1]
                ),
                member_count=Subquery(
                    TeamMember.objects.filter(team_id=OuterRef("pk"))
                    .values("team_id")
                    .annotate(c=Count("id"))
                    .values("c")[:1],
                    output_field=IntegerField(),
                ),
            )
            .order_by("created_at")
        )

        return [team async for team in queryset]

    @staticmethod
    async def update(team: Team, name: str, icon_id: UUID | None) -> Team:
        """Update and return the team's name and icon"""
        team.name = name
        team.icon_id = icon_id
        await team.asave(update_fields=["name", "icon_id"])
        return team

    @staticmethod
    def lock_sync(team_id: UUID) -> bool:
        """Lock the team row until the transaction ends. False if the team is deleted."""
        team = Team.objects.select_for_update().only("deleted_at").get(id=team_id)
        return team.deleted_at is None

    @staticmethod
    async def delete(team: Team) -> None:
        """Soft delete team."""
        team.deleted_at = timezone.now()
        await team.asave(update_fields=["deleted_at"])


class TeamMemberRepository:
    @staticmethod
    def create_sync(team: Team, user_id: UUID, role: str) -> TeamMember:
        """Create and return a team member."""
        return TeamMember.objects.create(team=team, user_id=user_id, role=role)

    @staticmethod
    async def get_member(team_id: UUID, user_id: UUID) -> TeamMember | None:
        """Return the membership row for this user, or None."""
        return await TeamMember.objects.filter(team_id=team_id, user_id=user_id).afirst()

    @staticmethod
    async def count_members(team_id: UUID) -> int:
        """Return the total number of members in a team."""
        return await TeamMember.objects.filter(team_id=team_id).acount()

    @staticmethod
    async def list_members(
        team_id: UUID, q: str | None, cursor: str | None, limit: int
    ) -> tuple[list[TeamMember], str | None]:
        """A page of the team directory, sorted by display name then user id."""
        qs = TeamMember.objects.filter(team_id=team_id).select_related("user")
        if q:
            qs = qs.filter(
                Q(user__display_name__istartswith=q) | Q(user__display_name__icontains=f" {q}")
            )
        return await paginate(
            qs, ("user__display_name", "user_id"), cursor, limit, "team_members", q
        )

    @staticmethod
    async def list_members_by_user_ids(team_id: UUID, user_ids: list[UUID]) -> list[TeamMember]:
        """These users' memberships in the team. User who aren't in it are left out."""
        qs = TeamMember.objects.filter(team_id=team_id, user_id__in=user_ids).select_related("user")
        return [m async for m in qs.order_by("user__display_name", "user_id")]

    @staticmethod
    def lock_owner_ids_sync(team_id: UUID) -> list[UUID]:
        """Lock the team row until the transaction ends, then return its owners' user ids.

        Locking the team, not the owner rows, makes a second change wait for the first one
        and then see its result (a member just promoted or demoted).
        """
        TeamRepository.lock_sync(team_id)
        return list(
            TeamMember.objects.filter(team_id=team_id, role=TeamMember.Role.OWNER).values_list(
                "user_id", flat=True
            )
        )

    @staticmethod
    def get_member_sync(team_id: UUID, user_id: UUID) -> TeamMember | None:
        return TeamMember.objects.filter(team_id=team_id, user_id=user_id).first()

    @staticmethod
    def update_role_sync(member: TeamMember, role: str) -> None:
        member.role = role
        member.save(update_fields=["role"])

    @staticmethod
    def delete_sync(team_id: UUID, user_id: UUID) -> None:
        TeamMember.objects.filter(team_id=team_id, user_id=user_id).delete()


class InviteRepository:
    @staticmethod
    async def get_by_id(invite_id: UUID) -> Invite | None:
        """Return an invite by id, or None."""
        return await Invite.objects.filter(id=invite_id).afirst()

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
    def count_active_sync(team_id: UUID) -> int:
        """Count active invites for the team. Locks the team row so a concurrent create
        can't race past the 100-invite cap check."""
        Team.objects.select_for_update().get(id=team_id)
        return InviteRepository._active_qs(team_id).count()

    @staticmethod
    def code_exists_sync(code: str) -> bool:
        """Check whether an invite with this code already exists."""
        return Invite.objects.filter(code=code).exists()

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
    async def list_active(team_id: UUID, created_by_id: UUID | None = None) -> list[Invite]:
        """Active invites for the team. Pass created_by_id to restrict to one user's invites."""
        qs = InviteRepository._active_qs(team_id).order_by("created_at")
        if created_by_id is not None:
            qs = qs.filter(created_by_id=created_by_id)
        return [invite async for invite in qs]

    @staticmethod
    async def revoke(invite: Invite) -> None:
        """Set revoked_at to now."""
        invite.revoked_at = timezone.now()
        await invite.asave(update_fields=["revoked_at"])

    @staticmethod
    def lock_by_id_sync(invite_id: UUID) -> Invite:
        """Lock the invite row until the transaction ends, and return it."""
        return Invite.objects.select_for_update().get(id=invite_id)

    @staticmethod
    def increment_uses_sync(invite: Invite) -> None:
        """Add 1 to uses. Call only with row locked."""
        invite.uses += 1
        invite.save(update_fields=["uses"])
