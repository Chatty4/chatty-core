from typing import Literal
from uuid import UUID

from channels import access
from channels.repositories import ChannelMemberRepository, ChannelRepository
from channels.schemas import ChannelAccess
from shared.codes import ErrorCode
from shared.exceptions import Conflict, NotFound, PermissionDenied
from teams.repositories import TeamMemberRepository

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
