from uuid import UUID

from django.db.models import Count
from django.utils import timezone

from channels.models import Channel
from shared.pagination import paginate
from teams.models import Team


class ChannelRepository:
    @staticmethod
    async def get_with_team(channel_id: UUID) -> Channel | None:
        """The channel with its team loaded, or None if it doesn't exist or its team was deleted."""
        return (
            await Channel.objects.select_related("team")
            .filter(id=channel_id, team__deleted_at__isnull=True)
            .afirst()
        )

    @staticmethod
    async def find_dm(team_id: UUID, dm_key: str) -> Channel | None:
        """The team's DM between exactly these people, or None."""
        return await Channel.objects.filter(
            team_id=team_id, kind=Channel.Kind.DM, dm_key=dm_key
        ).afirst()

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
    def list_default_ids_sync(team_id: UUID) -> list[UUID]:
        """Ids of the team's default channels that aren't archived."""
        return list(
            Channel.objects.filter(
                team_id=team_id, is_default=True, archived_at__isnull=True
            ).values_list("id", flat=True)
        )

    @staticmethod
    def create_sync(
        team: Team,
        name: str,
        kind: str,
        is_default: bool,
        created_by_id: UUID,
        topic: str = "",
        dm_key: str = "",
    ) -> Channel:
        """Create and return a channel."""
        return Channel.objects.create(
            team=team,
            name=name,
            kind=kind,
            is_default=is_default,
            created_by_id=created_by_id,
            topic=topic,
            dm_key=dm_key,
        )

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
