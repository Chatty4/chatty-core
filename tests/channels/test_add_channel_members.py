import uuid

import pytest
from django.utils import timezone

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
    return await make_user("owner@example.com")


@pytest.fixture
async def team(owner):
    return await TeamService.create("Backend", owner.id)


@pytest.fixture
async def member(team):
    """In the team, not in any channel."""
    return await team_member(team, "member@example.com")


async def add_to(channel_id, user) -> ChannelMember:
    return await ChannelMember.objects.acreate(
        channel_id=channel_id, user=user, notify_level=ChannelMember.NotifyLevel.ALL
    )


async def add_members(client, channel_id, as_user, user_ids):
    return await client.post(
        f"/api/core/v1/channels/{channel_id}/members",
        {"user_ids": [str(u) for u in user_ids]},
        content_type="application/json",
        headers=await headers_for(as_user),
    )


async def test_adds_new_people_and_skips_members(async_client, team, owner, member):
    other = await team_member(team, "other@example.com")
    await add_to(team.general_channel_id, member)

    response = await add_members(
        async_client, team.general_channel_id, owner, [member.id, other.id]
    )

    assert response.status_code == 200
    assert response.json() == {"added": [str(other.id)], "already_members": [str(member.id)]}
    added = await ChannelMember.objects.aget(channel_id=team.general_channel_id, user=other)
    assert added.role == "member"


async def test_duplicate_ids_are_added_once(async_client, team, owner, member):
    response = await add_members(
        async_client, team.general_channel_id, owner, [member.id, member.id]
    )

    assert response.json() == {"added": [str(member.id)], "already_members": []}


async def test_someone_outside_the_team_adds_nobody(async_client, team, owner, member):
    outsider = await make_user("out@example.com")

    response = await add_members(
        async_client, team.general_channel_id, owner, [member.id, outsider.id]
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "user_not_in_team"
    assert await ChannelMember.objects.filter(channel_id=team.general_channel_id).acount() == 1


async def test_cannot_add_to_dm(async_client, team, owner, member):
    dm = await Channel.objects.acreate(team_id=team.id, kind=Channel.Kind.DM, dm_key="x")
    await add_to(dm.id, owner)

    response = await add_members(async_client, dm.id, owner, [member.id])

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "not_allowed_for_dm"


async def test_non_member_cannot_add(async_client, team, owner, member):
    secret = await Channel.objects.acreate(
        team_id=team.id, name="secret", kind=Channel.Kind.PRIVATE
    )

    response = await add_members(async_client, secret.id, member, [owner.id])

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_a_member"


async def test_cannot_add_to_archived_channel(async_client, team, owner, member):
    old = await Channel.objects.acreate(
        team_id=team.id, name="old", kind=Channel.Kind.PUBLIC, archived_at=timezone.now()
    )
    await add_to(old.id, owner)

    response = await add_members(async_client, old.id, owner, [member.id])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "channel_archived"


async def test_empty_list_is_rejected(async_client, team, owner):
    response = await add_members(async_client, team.general_channel_id, owner, [])

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


async def test_missing_channel_is_404(async_client, owner, member):
    response = await add_members(async_client, uuid.uuid4(), owner, [member.id])

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "channel_not_found"
