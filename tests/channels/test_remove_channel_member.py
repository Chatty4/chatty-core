import uuid

import pytest

from channels.models import Channel, ChannelMember
from teams.models import TeamMember
from teams.services import TeamService
from tests.helpers import headers_for, make_user
from users.models import User

pytestmark = pytest.mark.django_db(transaction=True)


async def team_member(team, email: str) -> User:
    user = await make_user(email)
    await TeamMember.objects.acreate(team_id=team.id, user=user, role=TeamMember.Role.MEMBER)
    return user


@pytest.fixture
async def owner():
    """Team owner."""
    return await make_user("owner@example.com")


@pytest.fixture
async def team(owner):
    return await TeamService.create("Backend", owner.id)


@pytest.fixture
async def member(team):
    return await team_member(team, "member@example.com")


@pytest.fixture
async def secret(team):
    """Private channel the team owner is not in."""
    return await Channel.objects.acreate(team_id=team.id, name="secret", kind=Channel.Kind.PRIVATE)


async def add_to(channel_id, user, role=ChannelMember.Role.MEMBER) -> ChannelMember:
    return await ChannelMember.objects.acreate(
        channel_id=channel_id, user=user, role=role, notify_level=ChannelMember.NotifyLevel.ALL
    )


async def remove(client, channel_id, target_id, as_user):
    return await client.delete(
        f"/api/core/v1/channels/{channel_id}/members/{target_id}",
        headers=await headers_for(as_user),
    )


async def is_in(channel_id, user) -> bool:
    return await ChannelMember.objects.filter(channel_id=channel_id, user=user).aexists()


async def test_channel_owner_removes_a_member(async_client, team, member, secret):
    other = await team_member(team, "other@example.com")
    await add_to(secret.id, member, ChannelMember.Role.OWNER)
    await add_to(secret.id, other)

    response = await remove(async_client, secret.id, other.id, member)

    assert response.status_code == 204
    assert not await is_in(secret.id, other)


async def test_team_owner_removes_from_channel_they_are_not_in(async_client, owner, member, secret):
    await add_to(secret.id, member)

    response = await remove(async_client, secret.id, member.id, owner)

    assert response.status_code == 204


async def test_removing_last_owner_of_private_channel_hands_off(
    async_client, team, owner, member, secret
):
    other = await team_member(team, "other@example.com")
    await add_to(secret.id, member, ChannelMember.Role.OWNER)
    await add_to(secret.id, other)

    await remove(async_client, secret.id, member.id, owner)

    promoted = await ChannelMember.objects.aget(channel_id=secret.id, user=other)
    assert promoted.role == "owner"


async def test_plain_member_cannot_remove(async_client, team, member, secret):
    other = await team_member(team, "other@example.com")
    await add_to(secret.id, member)
    await add_to(secret.id, other)

    response = await remove(async_client, secret.id, other.id, member)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


async def test_removing_myself_says_use_leave(async_client, team, owner):
    response = await remove(async_client, team.general_channel_id, owner.id, owner)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "use_leave"


async def test_target_not_in_channel_is_404(async_client, team, owner, member):
    response = await remove(async_client, team.general_channel_id, member.id, owner)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "member_not_found"


async def test_cannot_remove_from_dm(async_client, team, owner, member):
    dm = await Channel.objects.acreate(team_id=team.id, kind=Channel.Kind.DM, dm_key="x")
    await add_to(dm.id, member)

    response = await remove(async_client, dm.id, member.id, owner)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "not_allowed_for_dm"


async def test_missing_channel_is_404(async_client, owner, member):
    response = await remove(async_client, uuid.uuid4(), member.id, owner)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "channel_not_found"


async def test_stranger_gets_forbidden_on_a_dm(async_client, team, member):
    dm = await Channel.objects.acreate(team_id=team.id, kind=Channel.Kind.DM, dm_key="x")
    await add_to(dm.id, member)
    stranger = await make_user("stranger@example.com")

    response = await remove(async_client, dm.id, member.id, stranger)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


async def test_stranger_removing_themselves_gets_forbidden(async_client, team):
    stranger = await make_user("stranger@example.com")

    response = await remove(async_client, team.general_channel_id, stranger.id, stranger)

    assert response.status_code == 403
