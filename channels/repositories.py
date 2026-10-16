from uuid import UUID

from django.db.models import Count
from django.utils import timezone

from channels.models import Channel, ChannelMember
from shared.pagination import paginate
from teams.models import Team


class ChannelRepository:
    @staticmethod
    def create_sync(
        team: Team, name: str, kind: str, is_default: bool, created_by_id: UUID, topic: str = ""
    ) -> Channel:
        """Create and return a channel."""
        return Channel.objects.create(
            team=team,
            name=name,
            kind=kind,
            is_default=is_default,
            created_by_id=created_by_id,
            topic=topic,
        )

    @staticmethod
    async def get_with_team(channel_id: UUID) -> Channel | None:
        """The channel with its team loaded, or None if it doesn't exist or its team was deleted."""
        return (
            await Channel.objects.select_related("team")
            .filter(id=channel_id, team__deleted_at__isnull=True)
            .afirst()
        )

    @staticmethod
    async def browse(
        team_id: UUID, user_id: UUID, q: str | None, cursor: str | None, limit: int
    ) -> tuple[list[Channel], str | None]:
        """A page of the team's public channels the user isn't in, each with member_count."""
        qs = Channel.objects.filter(team_id=team_id, kind=Channel.Kind.PUBLIC).exclude(
            members__user_id=user_id
        )
        if q:
            qs = qs.filter(name__icontains=q)
        qs = qs.annotate(member_count=Count("members"))
        return await paginate(qs, ("name", "id"), cursor, limit, "channel_browse", q)

    @staticmethod
    async def update(channel: Channel, name: str, topic: str) -> Channel:
        """Save the channel's name and topic. Raises IntegrityError if the name is taken."""
        channel.name = name
        channel.topic = topic
        await channel.asave(update_fields=["name", "topic"])
        return channel

    @staticmethod
    async def archive(channel: Channel) -> Channel:
        channel.archived_at = timezone.now()
        await channel.asave(update_fields=["archived_at"])
        return channel


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

    @staticmethod
    async def list_for_user_in_team(team_id: UUID, user_id: UUID) -> list[ChannelMember]:
        """My membership in the team's channels, each with its channel loaded."""
        qs = (
            ChannelMember.objects.filter(user_id=user_id, channel__team_id=team_id)
            .select_related("channel")
            .order_by("channel__name", "channel_id")
        )
        return [m async for m in qs]

    @staticmethod
    async def member_ids_by_channel(channel_ids: list[UUID]) -> dict[UUID, list[UUID]]:
        """{channel id: [user ids]} for these channels, in the order people joined."""
        result: dict[UUID, list[UUID]] = {}
        qs = (
            ChannelMember.objects.filter(channel_id__in=channel_ids)
            .order_by("joined_at")
            .values_list("channel_id", "user_id")
        )
        async for channel_id, user_id in qs:
            result.setdefault(channel_id, []).append(user_id)
        return result

    @staticmethod
    async def count(channel_id: UUID) -> int:
        return await ChannelMember.objects.filter(channel_id=channel_id).acount()

    @staticmethod
    async def get_or_create(channel_id: UUID, user_id: UUID, notify_level: str) -> ChannelMember:
        """
        The user's membership, created as a plain member if missing.
        Safe when two requests race.
        """
        member, _ = await ChannelMember.objects.aget_or_create(
            channel_id=channel_id, user_id=user_id, defaults={"notify_level": notify_level}
        )
        return member

    @staticmethod
    def lock_owner_ids_sync(channel_id: UUID) -> list[UUID]:
        """Lock the channel row until the transaction ends, then return its owners' user ids.

        Locking the channel, not the owner rows, makes a second leave wait for the first one's
        hand-off, so it sees the member who was just promoted.
        """
        Channel.objects.select_for_update().filter(id=channel_id).first()
        return list(
            ChannelMember.objects.filter(
                channel_id=channel_id, role=ChannelMember.Role.OWNER
            ).values_list("user_id", flat=True)
        )

    @staticmethod
    def delete_sync(channel_id: UUID, user_id: UUID) -> None:
        ChannelMember.objects.filter(channel_id=channel_id, user_id=user_id).delete()

    @staticmethod
    def promote_first_joined_sync(channel_id: UUID) -> None:
        """Make the member who joined first the owner. No-op when the channel is empty."""
        first = (
            ChannelMember.objects.filter(channel_id=channel_id)
            .order_by("joined_at", "user_id")
            .first()
        )
        if first:
            first.role = ChannelMember.Role.OWNER
            first.save(update_fields=["role"])

    @staticmethod
    async def page(
        channel_id: UUID, cursor: str | None, limit: int
    ) -> tuple[list[ChannelMember], str | None]:
        """A page of the channel's members, oldest first"""
        qs = ChannelMember.objects.filter(channel_id=channel_id)
        return await paginate(qs, ("joined_at", "user_id"), cursor, limit, "channel_members")

    @staticmethod
    async def add_many(channel_id: UUID, user_ids: list[UUID], notify_level: str) -> list[UUID]:
        """Add the users who aren't members yet. Return their ids, in the order given."""
        existing = {
            uid
            async for uid in ChannelMember.objects.filter(
                channel_id=channel_id, user_id__in=user_ids
            ).values_list("user_id", flat=True)
        }
        new_ids = [uid for uid in user_ids if uid not in existing]
        await ChannelMember.objects.abulk_create(
            [
                ChannelMember(channel_id=channel_id, user_id=uid, notify_level=notify_level)
                for uid in new_ids
            ],
            ignore_conflicts=True,  # someone joined or was added by another request meanwhile
        )
        return new_ids
