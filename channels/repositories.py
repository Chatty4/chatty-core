from uuid import UUID

from channels.models import Channel, ChannelMember
from teams.models import Team


class ChannelRepository:
    @staticmethod
    def create_sync(
        team: Team, name: str, kind: str, is_default: bool, created_by_id: UUID
    ) -> Channel:
        """Create and return a channel."""
        return Channel.objects.create(
            team=team, name=name, kind=kind, is_default=is_default, created_by_id=created_by_id
        )

    @staticmethod
    async def get_with_team(channel_id: UUID) -> Channel | None:
        """The channel with its team loaded, or None if it doesn't exist or its team was deleted."""
        return (
            await Channel.objects.select_related("team")
            .filter(id=channel_id, team__deleted_at__isnull=True)
            .afirst()
        )


class ChannelMemberRepository:
    @staticmethod
    def create_sync(channel: Channel, user_id: UUID, role: str, notify_level: str) -> ChannelMember:
        """Create and return a channel member."""
        return ChannelMember.objects.create(
            channel=channel, user_id=user_id, role=role, notify_level=notify_level
        )

    @staticmethod
    def delete_in_team_sync(team_id: UUID, user_id: UUID) -> None:
        """Remove the user from every channel of the team, DMs included."""
        ChannelMember.objects.filter(channel__team_id=team_id, user_id=user_id).delete()

    @staticmethod
    async def get_member(channel_id: UUID, user_id: UUID) -> ChannelMember | None:
        return await ChannelMember.objects.filter(channel_id=channel_id, user_id=user_id).afirst()
