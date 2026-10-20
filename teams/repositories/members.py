from uuid import UUID

from django.db.models import Case, Q, When

from shared.pagination import paginate
from teams.models import Invite, Team, TeamMember
from teams.repositories.teams import TeamRepository


class TeamMemberRepository:
    @staticmethod
    async def get_member(team_id: UUID, user_id: UUID) -> TeamMember | None:
        """Return the membership row for this user, or None."""
        return await TeamMember.objects.filter(team_id=team_id, user_id=user_id).afirst()

    @staticmethod
    def get_member_sync(team_id: UUID, user_id: UUID) -> TeamMember | None:
        return TeamMember.objects.filter(team_id=team_id, user_id=user_id).first()

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
    def list_owned_team_ids_sync(user_id: UUID) -> list[UUID]:
        """Ids of the live teams this user owns, sorted so their locks are always taken in the
        same order."""
        return list(
            TeamMember.objects.filter(
                user_id=user_id, role=TeamMember.Role.OWNER, team__deleted_at__isnull=True
            )
            .order_by("team_id")
            .values_list("team_id", flat=True)
        )

    @staticmethod
    def first_active_by_rank_sync(team_id: UUID) -> TeamMember | None:
        """The team's first active member by role (owner, then admin, then member), then by who
        joined first. None when nobody in the team is active."""
        rank = Case(
            When(role=TeamMember.Role.OWNER, then=0),
            When(role=TeamMember.Role.ADMIN, then=1),
            default=2,
        )
        return (
            TeamMember.objects.filter(team_id=team_id, user__is_active=True)
            .order_by(rank, "joined_at", "user_id")
            .first()
        )

    @staticmethod
    def create_sync(
        team: Team, user_id: UUID, role: str, invite: Invite | None = None
    ) -> TeamMember:
        """Create and return a team member. invite is the link they joined with, if any."""
        return TeamMember.objects.create(team=team, user_id=user_id, role=role, invite=invite)

    @staticmethod
    def update_role_sync(member: TeamMember, role: str) -> None:
        member.role = role
        member.save(update_fields=["role"])

    @staticmethod
    def delete_sync(team_id: UUID, user_id: UUID) -> None:
        TeamMember.objects.filter(team_id=team_id, user_id=user_id).delete()

    @staticmethod
    def lock_owner_ids_sync(team_id: UUID) -> list[UUID]:
        """Lock the team row until the transaction ends, then return its owners' user ids.

        Locking the team, not the owner rows, makes a second change wait for the first one
        and then see its result (a member just promoted or demoted).
        """
        TeamRepository.lock_sync(team_id)
        return list(
            TeamMember.objects.filter(
                team_id=team_id, role=TeamMember.Role.OWNER, user__is_active=True
            ).values_list("user_id", flat=True)
        )
