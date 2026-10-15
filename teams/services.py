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

MANAGERS = {TeamMember.Role.OWNER, TeamMember.Role.ADMIN}


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
        if user_ids is not None:  # lookup mode: exactly these members, never paginated
            return await TeamMemberRepository.list_members_by_user_ids(team_id, user_ids), None
        return await TeamMemberRepository.list_members(team_id, q, cursor, limit)

    @staticmethod
    async def change_role(team_id: UUID, user_id: UUID, target_id: UUID, role: str) -> TeamMember:
        me = await TeamService.require_member(team_id, user_id, roles=MANAGERS)
        return await sync_to_async(TeamService._change_role_sync)(team_id, me.role, target_id, role)

    @staticmethod
    @transaction.atomic
    def _change_role_sync(team_id: UUID, my_role: str, target_id: UUID, role: str) -> TeamMember:
        # Locking the owners first makes two concurent demotions run one after the other,
        # so they cna't both pas the last-owner check.
        owner_ids = TeamMemberRepository.lock_owner_ids_sync(team_id)
        target = TeamMemberRepository.get_member_sync(team_id, target_id)
        if target is None:
            raise NotFound(ErrorCode.MEMBER_NOT_FOUND)

        owner = TeamMember.Role.OWNER
        if my_role != owner and owner in (role, target.role):
            raise PermissionDenied()  # only an owner can make or change an owner
        if target.role == owner and role != owner and len(owner_ids) == 1:
            raise Conflict(ErrorCode.LAST_OWNER)

        TeamMemberRepository.update_role_sync(target, role)
        # TODO(CHAT-172): publish team.member.changed (role_changed) after commit

        return target

    @staticmethod
    async def remove_member(team_id: UUID, user_id: UUID, target_id: UUID) -> None:
        me = await TeamService.require_member(team_id, user_id, roles=MANAGERS)
        if target_id == user_id:
            raise Conflict(ErrorCode.USE_LEAVE)
        target = await TeamMemberRepository.get_member(team_id, target_id)
        if target is None:
            raise NotFound(ErrorCode.MEMBER_NOT_FOUND)
        if me.role != TeamMember.Role.OWNER and target.role == TeamMember.Role.OWNER:
            raise PermissionDenied()  # admins can't remove owners
        await sync_to_async(TeamService._remove_member_sync)(team_id, target_id)

    @staticmethod
    @transaction.atomic
    def _remove_member_sync(team_id: UUID, user_id: UUID) -> None:
        """Take the user out of a team and all its channes. Chat-155 (leave) can reuse it."""
        ChannelMemberRepository.delete_in_team_sync(team_id, user_id)
        TeamMemberRepository.delete_sync(team_id, user_id)
        # TODO(CHAT-172): publish team.member.changed (removed) after commit.
