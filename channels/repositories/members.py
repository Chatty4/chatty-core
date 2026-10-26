from uuid import UUID

from channels.models import Channel, ChannelMember
from shared.pagination import paginate


class ChannelMemberRepository:
    @staticmethod
    async def get_member(channel_id: UUID, user_id: UUID) -> ChannelMember | None:
        return await ChannelMember.objects.filter(channel_id=channel_id, user_id=user_id).afirst()

    @staticmethod
    async def count(channel_id: UUID) -> int:
        return await ChannelMember.objects.filter(channel_id=channel_id).acount()

    @staticmethod
    async def page(
        channel_id: UUID, cursor: str | None, limit: int
    ) -> tuple[list[ChannelMember], str | None]:
        """A page of the channel's members, oldest first"""
        qs = ChannelMember.objects.filter(channel_id=channel_id)
        return await paginate(qs, ("joined_at", "user_id"), cursor, limit, "channel_members")

    @staticmethod
    async def list_all(channel_id: UUID) -> list[ChannelMember]:
        """Every member of the channel, in the order they joined. Not paginated."""
        qs = ChannelMember.objects.filter(channel_id=channel_id).order_by("joined_at", "user_id")
        return [m async for m in qs]

    @staticmethod
    async def list_for_user_in_teams(team_ids: list[UUID], user_id: UUID) -> list[ChannelMember]:
        """My membership in these teams' channels, each with its channel loaded."""
        qs = (
            ChannelMember.objects.filter(user_id=user_id, channel__team_id__in=team_ids)
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
    def list_channel_ids_sync(team_id: UUID, user_id: UUID) -> list[UUID]:
        """Every channel of the team the user is in, DMs included, ordered by id."""
        return list(
            ChannelMember.objects.filter(user_id=user_id, channel__team_id=team_id)
            .order_by("channel_id")
            .values_list("channel_id", flat=True)
        )

    @staticmethod
    def list_private_channel_ids_sync(team_id: UUID, user_id: UUID) -> list[UUID]:
        """The team's private channels the user is in, ordered by id so their locks are always
        taken in the same order."""
        return list(
            ChannelMember.objects.filter(
                user_id=user_id, channel__team_id=team_id, channel__kind=Channel.Kind.PRIVATE
            )
            .order_by("channel_id")
            .values_list("channel_id", flat=True)
        )

    @staticmethod
    def create_sync(channel: Channel, user_id: UUID, role: str, notify_level: str) -> ChannelMember:
        """Create and return a channel member."""
        return ChannelMember.objects.create(
            channel=channel, user_id=user_id, role=role, notify_level=notify_level
        )

    @staticmethod
    async def get_or_create(
        channel_id: UUID, user_id: UUID, notify_level: str
    ) -> tuple[ChannelMember, bool]:
        """The user's membership, created as a plain member if missing, and whether it was
        created. Safe when two requests race."""
        return await ChannelMember.objects.aget_or_create(
            channel_id=channel_id, user_id=user_id, defaults={"notify_level": notify_level}
        )

    @staticmethod
    async def add_many(channel_id: UUID, user_ids: list[UUID], notify_level: str) -> list[UUID]:
        """Add the users who aren't members yet.
        Return the ids actually added, in the order given."""
        members = [
            ChannelMember(channel_id=channel_id, user_id=uid, notify_level=notify_level)
            for uid in user_ids
        ]
        # existing members, and anyone a parallel request just added, are skipped by the unique key
        await ChannelMember.objects.abulk_create(members, ignore_conflicts=True)
        # only rows inserted here carry the ids generated above
        inserted = {
            uid
            async for uid in ChannelMember.objects.filter(
                id__in=[m.id for m in members]
            ).values_list("user_id", flat=True)
        }
        return [uid for uid in user_ids if uid in inserted]

    @staticmethod
    def bulk_create_sync(
        channel_ids: list[UUID], user_id: UUID, role: str, notify_level: str
    ) -> None:
        """Add the user to each of these channels."""
        ChannelMember.objects.bulk_create(
            [
                ChannelMember(
                    channel_id=channel_id, user_id=user_id, role=role, notify_level=notify_level
                )
                for channel_id in channel_ids
            ],
            ignore_conflicts=True,
        )

    @staticmethod
    async def update_settings(
        member: ChannelMember, notify_level: str, muted: bool, hidden: bool
    ) -> ChannelMember:
        """Update channel settings for member."""
        member.notify_level = notify_level
        member.muted = muted
        member.hidden = hidden
        await member.asave(update_fields=["notify_level", "muted", "hidden"])
        return member

    @staticmethod
    def promote_first_joined_sync(channel_id: UUID) -> UUID | None:
        """Make the active member who joined first the owner, and return their user id. None when
        no active member is left."""
        first = (
            ChannelMember.objects.filter(channel_id=channel_id, user__is_active=True)
            .order_by("joined_at", "user_id")
            .first()
        )
        if first is None:
            return None
        first.role = ChannelMember.Role.OWNER
        first.save(update_fields=["role"])
        return first.user_id  # type: ignore[attr-defined]

    @staticmethod
    def delete_sync(channel_id: UUID, user_id: UUID) -> None:
        ChannelMember.objects.filter(channel_id=channel_id, user_id=user_id).delete()

    @staticmethod
    def delete_in_team_sync(team_id: UUID, user_id: UUID) -> None:
        """Remove the user from every channel of the team, DMs included."""
        ChannelMember.objects.filter(channel__team_id=team_id, user_id=user_id).delete()

    @staticmethod
    def lock_owner_ids_sync(channel_id: UUID) -> list[UUID]:
        """Lock the channel row until the transaction ends, then return its active owners' user
        ids. Deactivated owners don't count: they can't manage the channel.

        Locking the channel, not the owner rows, makes a second leave wait for the first one's
        hand-off, so it sees the member who was just promoted.
        """
        Channel.objects.select_for_update().filter(id=channel_id).first()
        return list(
            ChannelMember.objects.filter(
                channel_id=channel_id,
                role=ChannelMember.Role.OWNER,
                user__is_active=True,
            ).values_list("user_id", flat=True)
        )
