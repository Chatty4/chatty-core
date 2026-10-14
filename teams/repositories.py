from uuid import UUID

from django.db.models import Count, IntegerField, OuterRef, Subquery

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
