import uuid

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from channels.models import Channel, ChannelMember
from channels.services import ChannelService
from shared.codes import ErrorCode
from shared.exceptions import Conflict, NotFound, PermissionDenied
from teams.models import Team, TeamMember
from teams.services import TeamService
from users.models import User

pytestmark = pytest.mark.django_db(transaction=True)


async def make_user(email: str) -> User:
    return await sync_to_async(User.objects.create_user)(
        email=email, display_name="Ana Pop", password="correct horse battery"
    )


@pytest.fixture
async def owner():
    return await make_user("owner@example.com")


@pytest.fixture
async def team(owner):
    """A team whose owner is in the public general channel."""
    return await TeamService.create("Backend", owner.id)


@pytest.fixture
async def member(team):
    """In the team, not in any channel."""
    user = await make_user("member@example.com")
    await TeamMember.objects.acreate(team_id=team.id, user=user, role=TeamMember.Role.MEMBER)
    return user


@pytest.fixture
async def private(team):
    """A private channel nobody is in."""
    return await Channel.objects.acreate(team_id=team.id, name="secret", kind=Channel.Kind.PRIVATE)


async def join(channel_id, user) -> None:
    await ChannelMember.objects.acreate(
        channel_id=channel_id,
        user=user,
        role=ChannelMember.Role.MEMBER,
        notify_level=ChannelMember.NotifyLevel.MENTIONS,
    )


async def test_unknown_channel_is_not_found(owner):
    with pytest.raises(NotFound) as caught:
        await ChannelService.require_access(uuid.uuid4(), owner.id, "read")

    assert caught.value.code == ErrorCode.CHANNEL_NOT_FOUND


async def test_channel_of_a_deleted_team_is_not_found(owner, team):
    await Team.objects.filter(id=team.id).aupdate(deleted_at=timezone.now())

    with pytest.raises(NotFound) as caught:
        await ChannelService.require_access(team.general_channel_id, owner.id, "read")

    assert caught.value.code == ErrorCode.CHANNEL_NOT_FOUND


async def test_team_member_reads_a_public_channel_they_havent_joined(team, member):
    result = await ChannelService.require_access(team.general_channel_id, member.id, "read")

    assert result.channel.id == team.general_channel_id
    assert result.team_member.role == TeamMember.Role.MEMBER
    assert result.channel_member is None
    assert result.channel.team.name == "Backend"  # team loaded, no hidden query


@pytest.mark.parametrize("who", ["member", "outsider"])
async def test_cannot_read_a_private_channel_without_being_in_it(team, member, private, who):
    user = member if who == "member" else await make_user("out@example.com")

    with pytest.raises(PermissionDenied) as caught:
        await ChannelService.require_access(private.id, user.id, "read")

    assert caught.value.code == ErrorCode.CANNOT_READ_CHANNEL


@pytest.mark.parametrize("need", ["member", "write"])
async def test_not_in_the_channel_is_not_a_member(team, member, need):
    with pytest.raises(PermissionDenied) as caught:
        await ChannelService.require_access(team.general_channel_id, member.id, need)

    assert caught.value.code == ErrorCode.NOT_A_MEMBER


async def test_writing_to_an_archived_channel_is_a_conflict(team, member):
    await join(team.general_channel_id, member)
    await Channel.objects.filter(id=team.general_channel_id).aupdate(archived_at=timezone.now())

    with pytest.raises(Conflict) as caught:
        await ChannelService.require_access(team.general_channel_id, member.id, "write")

    assert caught.value.code == ErrorCode.CHANNEL_ARCHIVED


async def test_channel_member_can_write(team, member):
    await join(team.general_channel_id, member)

    result = await ChannelService.require_access(team.general_channel_id, member.id, "write")

    assert result.channel_member is not None


async def test_plain_member_cannot_manage(team, member):
    await join(team.general_channel_id, member)

    with pytest.raises(PermissionDenied) as caught:
        await ChannelService.require_access(team.general_channel_id, member.id, "manage")

    assert caught.value.code == ErrorCode.FORBIDDEN


async def test_team_owner_manages_a_private_channel_they_arent_in(owner, private):
    result = await ChannelService.require_access(private.id, owner.id, "manage")

    assert result.channel_member is None
