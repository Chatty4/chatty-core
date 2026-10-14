from uuid import UUID

from teams.models import Team, TeamMember


class TeamRepository:
    @staticmethod
    async def count_created_by(user_id: UUID) -> int:
        """Count non-deleted teams created by this user."""
        return await Team.objects.filter(created_by_id=user_id, deleted_at__isnull=True).acount()

    @staticmethod
    def create_sync(name: str, created_by_id: UUID) -> Team:
        """Create and return a new team."""
        return Team.objects.create(name=name, created_by_id=created_by_id)


class TeamMemberRepository:
    @staticmethod
    def create_sync(team: Team, user_id: UUID, role: str) -> TeamMember:
        """Create and return a team member."""
        return TeamMember.objects.create(team=team, user_id=user_id, role=role)
