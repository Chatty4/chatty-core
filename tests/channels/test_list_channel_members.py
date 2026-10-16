import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from channels.models import Channel, ChannelMember
from teams.models import TeamMember
from teams.services import TeamService
from tests.helpers import headers_for, make_user

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


async def add_to(channel_id, user, hours_later=0) -> ChannelMember:
    member = await ChannelMember.objects.acreate(
        channel_id=channel_id, user=user, notify_level=ChannelMember.NotifyLevel.ALL
    )
    if hours_later:  # auto_now_add ignores a passed joined_at, so set it after
        member.joined_at = timezone.now() + timedelta(hours=hours_later)
        await member.asave(update_fields=["joined_at"])
    return member


async def list_members(client, channel_id, as_user, **params):
    return await client.get(
        f"/api/core/v1/channels/{channel_id}/members", params, headers=await headers_for(as_user)
    )


async def test_lists_members_oldest_first(async_client, team, owner, member):
    await add_to(team.general_channel_id, member, hours_later=1)

    response = await list_members(async_client, team.general_channel_id, owner)

    assert response.status_code == 200
    body = response.json()
    assert [m["user_id"] for m in body["members"]] == [str(owner.id), str(member.id)]
    assert body["members"][0]["role"] == "owner"
    assert set(body["members"][0]) == {"user_id", "role", "joined_at"}
    assert body["next_cursor"] is None


async def test_team_member_lists_public_channel_they_havent_joined(async_client, team, member):
    response = await list_members(async_client, team.general_channel_id, member)

    assert response.status_code == 200


async def test_pages_follow_next_cursor(async_client, team, owner, member):
    third = await make_user("third@example.com")
    await add_to(team.general_channel_id, member, hours_later=1)
    await add_to(team.general_channel_id, third, hours_later=2)

    page1 = (await list_members(async_client, team.general_channel_id, owner, limit=2)).json()
    page2 = (
        await list_members(
            async_client, team.general_channel_id, owner, limit=2, cursor=page1["next_cursor"]
        )
    ).json()

    assert [m["user_id"] for m in page1["members"]] == [str(owner.id), str(member.id)]
    assert [m["user_id"] for m in page2["members"]] == [str(third.id)]
    assert page2["next_cursor"] is None


async def test_private_channel_im_not_in_is_forbidden(async_client, team, member):
    secret = await Channel.objects.acreate(
        team_id=team.id, name="secret", kind=Channel.Kind.PRIVATE
    )

    response = await list_members(async_client, secret.id, member)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "cannot_read_channel"


async def test_invalid_cursor_is_400(async_client, team, owner):
    response = await list_members(async_client, team.general_channel_id, owner, cursor="junk")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_cursor"


async def test_missing_channel_is_404(async_client, member):
    response = await list_members(async_client, uuid.uuid4(), member)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "channel_not_found"
