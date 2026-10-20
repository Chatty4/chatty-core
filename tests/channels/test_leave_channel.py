import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from channels.models import Channel, ChannelMember
from channels.services import ChannelService
from teams.models import TeamMember
from teams.services import TeamService
from tests.helpers import headers_for, make_user
from users.models import User

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
async def owner():
    return await make_user("owner@example.com")


@pytest.fixture
async def team(owner):
    return await TeamService.create("Backend", owner.id)


@pytest.fixture
async def member(team):
    """In the team, not in any channel."""
    user = await make_user("member@example.com")
    await TeamMember.objects.acreate(team_id=team.id, user=user, role=TeamMember.Role.MEMBER)
    return user


async def add_to(channel_id, user, role=ChannelMember.Role.MEMBER) -> ChannelMember:
    return await ChannelMember.objects.acreate(
        channel_id=channel_id, user=user, role=role, notify_level=ChannelMember.NotifyLevel.ALL
    )


async def leave(client, channel_id, as_user):
    return await client.post(
        f"/api/core/v1/channels/{channel_id}/leave", headers=await headers_for(as_user)
    )


async def role_of(channel_id, user) -> str:
    member = await ChannelMember.objects.aget(channel_id=channel_id, user=user)
    return member.role


async def test_member_leaves_a_public_channel(async_client, team, member):
    await add_to(team.general_channel_id, member)

    response = await leave(async_client, team.general_channel_id, member)

    assert response.status_code == 204
    assert not await ChannelMember.objects.filter(
        channel_id=team.general_channel_id, user=member
    ).aexists()


async def test_last_owner_of_private_channel_hands_off_to_first_joined(
    async_client, team, owner, member
):
    later = await make_user("later@example.com")
    secret = await Channel.objects.acreate(
        team_id=team.id, name="secret", kind=Channel.Kind.PRIVATE
    )
    await add_to(secret.id, owner, ChannelMember.Role.OWNER)
    await add_to(secret.id, member)
    late = await add_to(secret.id, later)
    await ChannelMember.objects.filter(pk=late.pk).aupdate(
        joined_at=timezone.now() + timedelta(hours=1)
    )

    response = await leave(async_client, secret.id, owner)

    assert response.status_code == 204
    assert await role_of(secret.id, member) == "owner"
    assert await role_of(secret.id, later) == "member"


async def test_no_hand_off_when_another_owner_stays(async_client, team, owner, member):
    co_owner = await make_user("co@example.com")
    secret = await Channel.objects.acreate(
        team_id=team.id, name="secret", kind=Channel.Kind.PRIVATE
    )
    await add_to(secret.id, owner, ChannelMember.Role.OWNER)
    await add_to(secret.id, co_owner, ChannelMember.Role.OWNER)
    await add_to(secret.id, member)

    await leave(async_client, secret.id, owner)

    assert await role_of(secret.id, member) == "member"


async def test_no_hand_off_in_public_channel(async_client, team, owner, member):
    await add_to(team.general_channel_id, member)

    await leave(async_client, team.general_channel_id, owner)

    assert await role_of(team.general_channel_id, member) == "member"


async def test_cannot_leave_dm(async_client, team, owner):
    dm = await Channel.objects.acreate(team_id=team.id, kind=Channel.Kind.DM, dm_key="x")
    await add_to(dm.id, owner)

    response = await leave(async_client, dm.id, owner)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "cannot_leave_dm"


async def test_non_member_cannot_leave(async_client, team, member):
    response = await leave(async_client, team.general_channel_id, member)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_a_member"


async def test_missing_channel_is_404(async_client, member):
    response = await leave(async_client, uuid.uuid4(), member)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "channel_not_found"


async def deactivate(user) -> None:
    await User.objects.filter(id=user.id).aupdate(is_active=False)


async def private_channel(team) -> Channel:
    return await Channel.objects.acreate(team_id=team.id, name="secret", kind=Channel.Kind.PRIVATE)


async def test_deactivated_co_owner_does_not_block_hand_off(async_client, team, owner, member):
    gone = await make_user("gone@example.com")
    secret = await private_channel(team)
    await add_to(secret.id, owner, ChannelMember.Role.OWNER)
    await add_to(secret.id, gone, ChannelMember.Role.OWNER)
    await add_to(secret.id, member)
    await deactivate(gone)

    await leave(async_client, secret.id, owner)

    assert await role_of(secret.id, member) == "owner"


async def test_hand_off_skips_deactivated_members(async_client, team, owner, member):
    gone = await make_user("gone@example.com")
    secret = await private_channel(team)
    await add_to(secret.id, owner, ChannelMember.Role.OWNER)
    await add_to(secret.id, gone)  # joined before member
    late = await add_to(secret.id, member)
    await ChannelMember.objects.filter(pk=late.pk).aupdate(
        joined_at=timezone.now() + timedelta(hours=1)
    )
    await deactivate(gone)

    await leave(async_client, secret.id, owner)

    assert await role_of(secret.id, member) == "owner"
    assert await role_of(secret.id, gone) == "member"


async def test_removing_deactivated_sole_owner_still_hands_off(team, owner, member):
    gone = await make_user("gone@example.com")
    secret = await private_channel(team)
    await add_to(secret.id, gone, ChannelMember.Role.OWNER)
    await add_to(secret.id, member)
    await deactivate(gone)

    await ChannelService.remove_member(secret.id, owner.id, gone.id)

    assert await role_of(secret.id, member) == "owner"
