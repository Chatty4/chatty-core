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


@dataclass
class ChannelDetail:
    channel: Channel
    member_count: int
    my: ChannelMember | None  # None when I can read the channel but haven't joined it


@dataclass
class DMResult:
    channel: Channel
    member_ids: list[UUID]
    created: bool  # False when the DM already existed (200 instead of 201)


@dataclass
class InternalChannel:
    """One channel with all its members, for chatty-chat (GET /internal/channels/{id})."""

    channel: Channel  # with its team loaded
    members: list[ChannelMember]
