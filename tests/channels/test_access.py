from datetime import UTC, datetime

import pytest

from channels import access
from channels.models import Channel, ChannelMember
from teams.models import Team, TeamMember

NOW = datetime(2026, 10, 15, tzinfo=UTC)
PUBLIC, PRIVATE, DM = Channel.Kind.PUBLIC, Channel.Kind.PRIVATE, Channel.Kind.DM
T_OWNER, T_ADMIN, T_MEMBER = TeamMember.Role.OWNER, TeamMember.Role.ADMIN, TeamMember.Role.MEMBER
C_OWNER, C_MEMBER = ChannelMember.Role.OWNER, ChannelMember.Role.MEMBER


def setup(kind=PUBLIC, team_role=T_MEMBER, channel_role=None, archived=False, team_deleted=False):
    """Unsaved rows: the rules only read fields, so no database is needed."""
    team = Team(deleted_at=NOW if team_deleted else None)
    channel = Channel(team=team, kind=kind, archived_at=NOW if archived else None)
    team_member = TeamMember(role=team_role) if team_role else None
    channel_member = ChannelMember(role=channel_role) if channel_role else None
    return channel, team_member, channel_member


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        (dict(kind=PUBLIC), True),  # team member reads any public channel
        (dict(kind=PRIVATE), False),
        (dict(kind=DM), False),
        (dict(kind=PRIVATE, channel_role=C_MEMBER), True),
        (dict(kind=DM, channel_role=C_MEMBER), True),
        (dict(kind=PRIVATE, channel_role=C_MEMBER, archived=True), True),  # archived stays readable
        (dict(kind=PUBLIC, team_role=None), False),  # not in the team
        (dict(kind=PRIVATE, team_role=None, channel_role=C_MEMBER), False),  # leftover channel row
    ],
)
def test_can_read(case, expected):
    assert access.can_read(*setup(**case)) is expected


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        (dict(channel_role=C_MEMBER), True),
        (dict(channel_role=None), False),  # public channel I haven't joined
        (dict(channel_role=C_MEMBER, archived=True), False),
        (dict(channel_role=C_MEMBER, team_deleted=True), False),
        (dict(team_role=None, channel_role=C_MEMBER), False),  # leftover channel row
    ],
)
def test_can_write(case, expected):
    assert access.can_write(*setup(**case)) is expected


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        (dict(channel_role=C_OWNER), True),  # channel owner
        (dict(team_role=T_OWNER), True),  # team owner, not even in the channel
        (dict(team_role=T_ADMIN), True),
        (dict(channel_role=C_MEMBER), False),  # plain member
        (dict(kind=PRIVATE, team_role=T_ADMIN), True),
        (dict(kind=DM, team_role=T_OWNER), False),  # nobody manages a DM
        (dict(kind=DM, channel_role=C_OWNER), False),
        (dict(team_role=None, channel_role=C_OWNER), False),  # leftover channel row
    ],
)
def test_can_manage(case, expected):
    assert access.can_manage(*setup(**case)) is expected


@pytest.mark.parametrize(
    ("team_role", "channel_role", "expected"),
    [
        (T_MEMBER, C_MEMBER, True),
        (T_MEMBER, None, False),
        (None, C_MEMBER, False),
    ],
)
def test_is_member(team_role, channel_role, expected):
    _, team_member, channel_member = setup(team_role=team_role, channel_role=channel_role)

    assert access.is_member(team_member, channel_member) is expected
