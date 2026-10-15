from dataclasses import dataclass

from channels.models import Channel, ChannelMember
from teams.models import TeamMember


@dataclass
class ChannelAccess:
    """What require_access loaded, so callers don't query it again."""

    channel: Channel
    team_member: TeamMember
    channel_member: ChannelMember | None