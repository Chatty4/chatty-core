from uuid import UUID

from django.contrib.auth import get_user_model
from django.db.models import Count, IntegerField, OuterRef, Subquery
from django.utils import timezone

from teams.models import Team, TeamMember


class TeamRepository:
    @staticmethod
    async def get_by_id(team_id: UUID) -> Team | None:
        """Return a non-deleted team by id, or None."""
        return await Team.objects.filter(id=team_id, deleted_at__isnull=True).afirst()

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
    async def update(team: Team, name: str, icon_id: UUID | None) -> Team:
        """Update and return the team's name and icon"""
        team.name = name
        team.icon_id = icon_id
        await team.asave(update_fields=["name", "icon_id"])
        return team

    @staticmethod
    async def delete(team: Team) -> None:
        """Soft delete team."""
        team.deleted_at = timezone.now()
        await team.asave(update_fields=["deleted_at"])

    @staticmethod
    def lock_sync(team_id: UUID) -> bool:
        """Lock the team row until the transaction ends. False if the team is deleted."""
        team = Team.objects.select_for_update().only("deleted_at").get(id=team_id)
        return team.deleted_at is None
