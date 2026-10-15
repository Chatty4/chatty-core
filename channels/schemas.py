from dataclasses import dataclass
from uuid import UUID

from channels.models import Channel, ChannelMember
from teams.models import TeamMember


@dataclass
class ChannelAccess:
    """What require_access loaded, so callers don't query it again."""

    channel: Channel
    team_member: TeamMember
    channel_member: ChannelMember | None


@dataclass
class MyChannel:
    """One sidebar entry: the channel, my membership in it, and the poeple in it for DMs."""

    channel: Channel
    my: ChannelMember
    dm_member_ids: list[UUID] | None
