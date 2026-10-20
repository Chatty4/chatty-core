from typing import Literal
from uuid import UUID

from asgiref.sync import sync_to_async
from django.db import IntegrityError, transaction

from channels import access
from channels.models import Channel, ChannelMember
from channels.repositories import ChannelMemberRepository, ChannelRepository
from channels.schemas import ChannelAccess, ChannelDetail, DMResult, MyChannel
from shared.codes import ErrorCode
from shared.exceptions import BadRequest, Conflict, NotFound, PermissionDenied, ValidationFailed
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
        manage: forbidden outside the team, not_allowed_for_dm for a DM, else forbidden
        A missing channel, or one whose team was deleted, is channel_not_found.
        """
        channel = await ChannelRepository.get_with_team(channel_id)
        if channel is None:
            raise NotFound(ErrorCode.CHANNEL_NOT_FOUND)
        team_member = await TeamMemberRepository.get_member(channel.team.id, user_id)
        channel_member = await ChannelMemberRepository.get_member(channel_id, user_id)

        if need == "manage" and channel.kind == Channel.Kind.DM and team_member is not None:
            raise BadRequest(ErrorCode.NOT_ALLOWED_FOR_DM)
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

    @staticmethod
    async def leave(channel_id: UUID, user_id: UUID) -> None:
        access = await ChannelService.require_access(channel_id, user_id, "member")
        if access.channel.kind == Channel.Kind.DM:
            raise BadRequest(ErrorCode.CANNOT_LEAVE_DM)
        await sync_to_async(ChannelService._leave_sync)(access.channel, user_id)

    @staticmethod
    @transaction.atomic
    def _leave_sync(channel: Channel, user_id: UUID) -> None:
        """The owner lock stops two owners leaving at once from both skipping the hand-off."""
        owner_ids = ChannelMemberRepository.lock_owner_ids_sync(channel.id)
        ChannelMemberRepository.delete_sync(channel.id, user_id)
        # hand off when no active owner other than the one leaving is left
        if channel.kind == Channel.Kind.PRIVATE and set(owner_ids) <= {user_id}:
            ChannelMemberRepository.promote_first_joined_sync(channel.id)
        # TODO(CHAT-172): publish membership.changed (removed) after commit

    @staticmethod
    async def list_members(
        channel_id: UUID, user_id: UUID, limit: int, cursor: str | None = None
    ) -> tuple[list[ChannelMember], str | None]:
        await ChannelService.require_access(channel_id, user_id, "read")
        return await ChannelMemberRepository.page(channel_id, cursor, limit)

    @staticmethod
    async def add_members(
        channel_id: UUID, user_id: UUID, user_ids: list[UUID]
    ) -> tuple[list[UUID], list[UUID]]:
        """(added, already_members)"""
        access = await ChannelService.require_access(channel_id, user_id, "write")
        if access.channel.kind == Channel.Kind.DM:
            raise BadRequest(ErrorCode.NOT_ALLOWED_FOR_DM)
        user_ids = list(dict.fromkeys(user_ids))  # drop duplicates, keep order
        in_team = await TeamMemberRepository.list_members_by_user_ids(
            access.channel.team.id, user_ids
        )
        if len(in_team) != len(user_ids):
            raise BadRequest(ErrorCode.USER_NOT_IN_TEAM)
        added = await ChannelMemberRepository.add_many(
            channel_id, user_ids, ChannelMember.NotifyLevel.MENTIONS
        )
        # TODO(CHAT-172): publish membership.changed (added) for each id in 'added' after commit

        return added, [uid for uid in user_ids if uid not in added]

    @staticmethod
    async def remove_member(channel_id: UUID, user_id: UUID, target_id: UUID) -> None:
        access = await ChannelService.require_access(channel_id, user_id, "manage")
        if target_id == user_id:
            raise Conflict(ErrorCode.USE_LEAVE)
        if await ChannelMemberRepository.get_member(channel_id, target_id) is None:
            raise NotFound(ErrorCode.MEMBER_NOT_FOUND)
        # same as leave: removing the last owner of a private channel hands it off too
        await sync_to_async(ChannelService._leave_sync)(access.channel, target_id)

    @staticmethod
    async def update(
        channel_id: UUID, user_id: UUID, name: str, topic: str | None = None
    ) -> ChannelDetail:
        """Rename and change the topic. No topic keeps the current one."""
        access = await ChannelService.require_access(channel_id, user_id, "manage")
        if access.channel.archived_at is not None:
            raise Conflict(ErrorCode.CHANNEL_ARCHIVED)
        try:
            channel = await ChannelRepository.update(
                access.channel, name, access.channel.topic if topic is None else topic
            )
        except IntegrityError:  # unique_channel_name_per_team, also when two renames race
            raise Conflict(ErrorCode.CHANNEL_NAME_TAKEN) from None
        # TODO(CHAT-172): publish channel.updated after commit
        member_count = await ChannelMemberRepository.count(channel_id)
        return ChannelDetail(channel, member_count, access.channel_member)

    @staticmethod
    async def archive(channel_id: UUID, user_id: UUID) -> ChannelDetail:
        access = await ChannelService.require_access(channel_id, user_id, "manage")
        channel = access.channel
        if channel.is_default:
            raise BadRequest(ErrorCode.CANNOT_ARCHIVE_DEFAULT)
        if channel.archived_at is None:  # not archived yet. if it already is, return 200
            channel = await ChannelRepository.archive(channel)
            # TODO(CHAT-172): publish channel.updated (archived: true) after commit
        member_count = await ChannelMemberRepository.count(channel_id)
        return ChannelDetail(channel, member_count, access.channel_member)

    @staticmethod
    async def update_my_settings(
        channel_id: UUID, user_id: UUID, notify_level: str, muted: bool, hidden: bool
    ) -> ChannelMember:
        """My notification settings for a channel. Hidden is only for DMs."""
        # TODO(CHAT-172): publish membership.changed (settings) after commit.
        access = await ChannelService.require_access(channel_id, user_id, "member")
        member = access.channel_member
        assert member is not None  # require_access("member") raised otherwise

        if hidden and access.channel.kind != Channel.Kind.DM:
            raise ValidationFailed(fields={"hidden": "invalid"})

        return await ChannelMemberRepository.update_settings(member, notify_level, muted, hidden)

    @staticmethod
    async def open_dm(team_id: UUID, user_id: UUID, user_ids: list[UUID]) -> DMResult:
        """Open a DM with 1-7 other team members, or return the one these people already have."""
        team, _ = await TeamService.require_member(team_id, user_id)

        others = [uid for uid in dict.fromkeys(user_ids) if uid != user_id]
        if not 1 <= len(others) <= 7:
            raise ValidationFailed(fields={"user_ids": "invalid"})

        in_team = await TeamMemberRepository.list_members_by_user_ids(team_id, others)
        if len(in_team) != len(others):
            raise BadRequest(ErrorCode.USER_NOT_IN_TEAM)

        member_ids = [user_id, *others]
        dm_key = ":".join(sorted(str(uid) for uid in member_ids))

        channel = await ChannelRepository.find_dm(team_id, dm_key)
        created = False
        if channel is None:
            try:
                channel = await sync_to_async(ChannelService._create_dm_sync)(
                    team, user_id, member_ids, dm_key
                )
                created = True
            except IntegrityError:  # unique_dm_key_per_team: opened by someone else just now
                channel = await ChannelRepository.find_dm(team_id, dm_key)
                if channel is None:  # can't happen: DMs are never deleted
                    raise

        if not created:
            # people who left the team lost their DM membership; they get it back
            await ChannelMemberRepository.add_many(
                channel.id, member_ids, ChannelMember.NotifyLevel.ALL
            )

        ids = await ChannelMemberRepository.member_ids_by_channel([channel.id])
        return DMResult(channel, ids[channel.id], created)

    @staticmethod
    @transaction.atomic
    def _create_dm_sync(team: Team, user_id: UUID, member_ids: list[UUID], dm_key: str) -> Channel:
        """The DM and all its members in one transaction."""
        channel = ChannelRepository.create_sync(
            team=team,
            name="",
            kind=Channel.Kind.DM,
            is_default=False,
            created_by_id=user_id,
            dm_key=dm_key,
        )

        for member_id in member_ids:
            ChannelMemberRepository.create_sync(
                channel=channel,
                user_id=member_id,
                role=ChannelMember.Role.MEMBER,
                notify_level=ChannelMember.NotifyLevel.ALL,
            )

        # TODO(CHAT-172): publish membership.changed (added) for each member after commit

        return channel
