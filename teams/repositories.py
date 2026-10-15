from uuid import UUID

from django.db.models import Count, IntegerField, OuterRef, Q, Subquery

from shared.pagination import paginate
from teams.models import Team, TeamMember


class TeamRepository:
    @staticmethod
    async def get_by_id(team_id: UUID) -> Team | None:
        """Return a non-deleted team by id, or None."""
        return await Team.objects.filter(id=team_id, deleted_at__isnull=True).afirst()

    @staticmethod
    async def count_created_by(user_id: UUID) -> int:
        """Count non-deleted teams created by this user."""
        return await Team.objects.filter(created_by_id=user_id, deleted_at__isnull=True).acount()

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
        """Lock the team's owner rows until the transaction ends, and return their user ids."""
        return list(
            TeamMember.objects.select_for_update()
            .filter(team_id=team_id, role=TeamMember.Role.OWNER)
            .values_list("user_id", flat=True)
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
