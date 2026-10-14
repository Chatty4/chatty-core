from uuid import UUID

from asgiref.sync import sync_to_async
from django.db import transaction

from channels.models import Channel, ChannelMember
from channels.repositories import ChannelMemberRepository, ChannelRepository
from shared.codes import ErrorCode
from shared.exceptions import Conflict
from teams.models import TeamMember
from teams.repositories import TeamMemberRepository, TeamRepository
from teams.schemas import CreateTeamResult, TeamResult


class TeamService:
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
