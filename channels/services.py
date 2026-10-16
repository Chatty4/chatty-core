from typing import Literal
from uuid import UUID

from asgiref.sync import sync_to_async
from django.db import IntegrityError, transaction

from channels import access
from channels.models import Channel, ChannelMember
from channels.repositories import ChannelMemberRepository, ChannelRepository
from channels.schemas import ChannelAccess, ChannelDetail, MyChannel
from shared.codes import ErrorCode
from shared.exceptions import Conflict, NotFound, PermissionDenied
from teams.models import Team
from teams.repositories import TeamMemberRepository
from teams.services import TeamService

Need = Literal["read", "member", "write", "manage"]


class ChannelService:
    @staticmethod
    async def require_access(channel_id: UUID, user_id: UUID, need: Need) -> ChannelAccess:
        """Load the channel and my memberships, or raise the contract error for `need`.

        read:   cannot_read_channel
        member: not_a_member
        write:  not_a_member, or channel_archived
        manage: forbidden
        A missing channel, or one whose team was deleted, is channel_not_found.
        """
        channel = await ChannelRepository.get_with_team(channel_id)
        if channel is None:
            raise NotFound(ErrorCode.CHANNEL_NOT_FOUND)
        team_member = await TeamMemberRepository.get_member(channel.team.id, user_id)
        channel_member = await ChannelMemberRepository.get_member(channel_id, user_id)

        if need == "read" and not access.can_read(channel, team_member, channel_member):
            raise PermissionDenied(ErrorCode.CANNOT_READ_CHANNEL)
        if need in ("member", "write") and not access.is_member(team_member, channel_member):
            raise PermissionDenied(ErrorCode.NOT_A_MEMBER)
        if need == "write" and not access.can_write(channel, team_member, channel_member):
            raise Conflict(ErrorCode.CHANNEL_ARCHIVED)
        if need == "manage" and not access.can_manage(channel, team_member, channel_member):
            raise PermissionDenied()
        assert team_member is not None  # every need above requires the team
        return ChannelAccess(channel, team_member, channel_member)

    @staticmethod
    async def get(channel_id: UUID, user_id: UUID) -> ChannelDetail:
        access = await ChannelService.require_access(channel_id, user_id, "read")
        member_count = await ChannelMemberRepository.count(channel_id)
        return ChannelDetail(access.channel, member_count, access.channel_member)

    @staticmethod
    async def create(team_id: UUID, user_id: UUID, name: str, kind: str, topic: str) -> Channel:
        team, _ = await TeamService.require_member(team_id, user_id)
        try:
            return await sync_to_async(ChannelService._create_sync)(
                team, user_id, name, kind, topic
            )
        except IntegrityError:  # unique_channel_name_per_team, also when two requests race
            raise Conflict(ErrorCode.CHANNEL_NAME_TAKEN) from None

    @staticmethod
    @transaction.atomic
    def _create_sync(team: Team, user_id: UUID, name: str, kind: str, topic: str) -> Channel:
        channel = ChannelRepository.create_sync(
            team=team, name=name, kind=kind, is_default=False, created_by_id=user_id, topic=topic
        )
        ChannelMemberRepository.create_sync(
            channel=channel,
            user_id=user_id,
            role=ChannelMember.Role.OWNER,
            notify_level=ChannelMember.NotifyLevel.MENTIONS,
        )
        # TODO(CHAT-172): publish membership.changed (added) after commit
        return channel

    @staticmethod
    async def list_mine(team_id: UUID, user_id: UUID) -> list[MyChannel]:
        """The sidebar: every channel and DM I'm in, hidden DMs included"""
        await TeamService.require_member(team_id, user_id)
        memberships = await ChannelMemberRepository.list_for_user_in_team(team_id, user_id)
        dm_ids = [m.channel.id for m in memberships if m.channel.kind == Channel.Kind.DM]
        dm_members = await ChannelMemberRepository.member_ids_by_channel(dm_ids)
        return [
            MyChannel(
                channel=m.channel,
                my=m,
                dm_member_ids=dm_members.get(m.channel.id, []) if m.channel.id in dm_ids else None,
            )
            for m in memberships
        ]

    @staticmethod
    async def browse(
        team_id: UUID, user_id: UUID, limit: int, cursor: str | None = None, q: str | None = None
    ) -> tuple[list[Channel], str | None]:
        await TeamService.require_member(team_id, user_id)
        return await ChannelRepository.browse(team_id, user_id, q, cursor, limit)

    @staticmethod
    async def join(channel_id: UUID, user_id: UUID) -> ChannelMember:
        channel = await ChannelRepository.get_with_team(channel_id)
        if channel is None:
            raise NotFound(ErrorCode.CHANNEL_NOT_FOUND)
        await TeamService.require_member(channel.team.id, user_id)
        if channel.kind != Channel.Kind.PUBLIC:
            raise PermissionDenied(ErrorCode.CANNOT_JOIN_PRIVATE)
        if channel.archived_at is not None:
            raise Conflict(ErrorCode.CHANNEL_ARCHIVED)
        # TODO(CHAT-172): publish membership.changed (added) after commit, only when newly created

        return await ChannelMemberRepository.get_or_create(
            channel_id, user_id, ChannelMember.NotifyLevel.MENTIONS
        )
