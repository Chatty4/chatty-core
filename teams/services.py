from uuid import UUID

from asgiref.sync import sync_to_async
from django.db import transaction

from channels.models import Channel, ChannelMember
from channels.repositories import ChannelMemberRepository, ChannelRepository
from shared.codes import ErrorCode
from shared.exceptions import Conflict, NotFound, PermissionDenied
from teams.models import Team, TeamMember
from teams.repositories import TeamMemberRepository, TeamRepository
from teams.schemas import CreateTeamResult, TeamResult


class TeamService:
    @staticmethod
    async def _get_team_or_404(team_id: UUID) -> Team:
        team = await TeamRepository.get_by_id(team_id)
        if team is None:
            raise NotFound(ErrorCode.TEAM_NOT_FOUND)
        return team

    @staticmethod
    async def _get_member_or_403(team_id: UUID, user_id: UUID) -> TeamMember:
        member = await TeamMemberRepository.get_member(team_id, user_id)
        if member is None:
            raise PermissionDenied(ErrorCode.NOT_A_TEAM_MEMBER)
        return member

    @staticmethod
    async def create(name: str, user_id: UUID) -> CreateTeamResult:
        if await TeamRepository.count_created_by(user_id) >= 10:
            raise Conflict(ErrorCode.TEAM_LIMIT_REACHED)
        return await sync_to_async(TeamService._create_sync)(name, user_id)

    @staticmethod
    @transaction.atomic
    def _create_sync(name: str, user_id: UUID) -> CreateTeamResult:
        team = TeamRepository.create_sync(name, created_by_id=user_id)
        TeamMemberRepository.create_sync(team=team, user_id=user_id, role=TeamMember.Role.OWNER)
        channel = ChannelRepository.create_sync(
            team=team,
            name="general",
            kind=Channel.Kind.PUBLIC,
            is_default=True,
            created_by_id=user_id,
        )
        ChannelMemberRepository.create_sync(
            channel=channel,
            user_id=user_id,
            role=ChannelMember.Role.OWNER,
            notify_level=ChannelMember.NotifyLevel.MENTIONS,
        )
        return CreateTeamResult(
            id=team.id,
            name=team.name,
            icon_file_id=team.icon_id,
            role=TeamMember.Role.OWNER,
            member_count=1,
            general_channel_id=channel.id,
            created_at=team.created_at,
        )

    @staticmethod
    async def list_for_user(user_id: UUID) -> list[TeamResult]:
        teams = await TeamRepository.list_by_user(user_id)
        return [
            TeamResult(
                id=team.id,
                name=team.name,
                icon_file_id=team.icon_id,
                role=team.role,  # type: ignore[attr-defined]
                member_count=team.member_count,  # type: ignore[attr-defined]
                created_at=team.created_at,
            )
            for team in teams
        ]

    @staticmethod
    async def get(team_id: UUID, user_id: UUID) -> TeamResult:
        team = await TeamService._get_team_or_404(team_id)
        member = await TeamService._get_member_or_403(team_id, user_id)
        count = await TeamMemberRepository.count_members(team_id)
        return TeamResult(
            id=team.id,
            name=team.name,
            icon_file_id=team.icon_id,
            role=member.role,
            member_count=count,
            created_at=team.created_at,
        )

    @staticmethod
    async def require_member(
        team_id: UUID, user_id: UUID, roles: set[TeamMember.Role] | None = None
    ) -> TeamMember:
        """The user's membership in a live team. Every /teams/{team_id}/... endpoint starts here.

        Raises team_not_found, not_a_team_member, or forbidden when `roles` is given and the
        user's role isn't in it.
        """
        await TeamService._get_team_or_404(team_id)
        member = await TeamService._get_member_or_403(team_id, user_id)
        if roles is not None and member.role not in roles:
            raise PermissionDenied()
        return member

    @staticmethod
    async def list_members(
        team_id: UUID,
        user_id: UUID,
        limit: int,
        cursor: str | None = None,
        q: str | None = None,
        user_ids: list[UUID] | None = None,
    ) -> tuple[list[TeamMember], str | None]:
        await TeamService.require_member(team_id, user_id)
        if user_ids is not None: # lookup mode: exactly these members, never paginated
            return await TeamMemberRepository.list_members_by_user_ids(team_id, user_ids), None
        return await TeamMemberRepository.list_members(team_id, q, cursor, limit)
