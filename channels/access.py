"""Who can read, write and manage a channel (api-chat.md "Who can read and write a channel").

Pure rules: they take rows that are already loaded and never query. `channel.team` must be
loaded (select_related) by the caller. The service layer turns a False into the contract error.
"""

from channels.models import Channel, ChannelMember
from teams.models import TeamMember


def is_member(team_member: TeamMember | None, channel_member: ChannelMember | None) -> bool:
    """In the channel (and therefore in the team)."""
    return team_member is not None and channel_member is not None


def can_read(
    channel: Channel, team_member: TeamMember | None, channel_member: ChannelMember | None
) -> bool:
    """A channel member, or any team member for a public channel.
    Archived channels stay readable.
    """
    if team_member is None:
        return False
    return channel_member is not None or channel.kind == Channel.Kind.PUBLIC


def can_write(
    channel: Channel, team_member: TeamMember | None, channel_member: ChannelMember | None
) -> bool:
    """A channel member, and the channel isn't archived and its team isn't deleted."""
    return (
        is_member(team_member, channel_member)
        and channel.archived_at is None
        and channel.team.deleted_at is None
    )


def can_manage(
    channel: Channel, team_member: TeamMember | None, channel_member: ChannelMember | None
) -> bool:
    """The channel owner, or a team owner or admin. DMs have no owner, so nobody manages them."""
    if team_member is None or channel.kind == Channel.Kind.DM:
        return False
    is_channel_owner = (
        channel_member is not None and channel_member.role == ChannelMember.Role.OWNER
    )
    return is_channel_owner or team_member.role in (TeamMember.Role.OWNER, TeamMember.Role.ADMIN)
