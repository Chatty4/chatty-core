import uuid

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from authn.services import AuthnService
from channels.models import Channel, ChannelMember
from teams.models import TeamMember
from teams.services import TeamService
from users.models import User

pytestmark = pytest.mark.django_db(transaction=True)


async def make_user(email: str) -> User:
    return await sync_to_async(User.objects.create_user)(
        email=email, display_name="Ana Pop", password="correct horse battery"
    )


async def headers_for(user: User) -> dict:
    tokens = await AuthnService().issue_tokens(user)
    return {"Authorization": f"Bearer {tokens.access_token}"}


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


async def join(client, channel_id, as_user):
    return await client.post(
        f"/api/core/v1/channels/{channel_id}/join", headers=await headers_for(as_user)
    )


async def test_team_member_joins_a_public_channel(async_client, team, member):
    response = await join(async_client, team.general_channel_id, member)

    assert response.status_code == 200
    assert response.json() == {
        "channel_id": str(team.general_channel_id),
        "role": "member",
        "notify_level": "mentions",
        "muted": False,
        "hidden": False,
    }
    assert await ChannelMember.objects.filter(
        channel_id=team.general_channel_id, user=member
    ).aexists()


async def test_joining_twice_returns_200_and_keeps_one_row(async_client, team, owner):
    response = await join(async_client, team.general_channel_id, owner)

    assert response.status_code == 200
    assert response.json()["role"] == "owner"  # existing membership, not a new one
    assert await ChannelMember.objects.filter(channel_id=team.general_channel_id).acount() == 1


async def test_outsider_cannot_join(async_client, team):
    outsider = await make_user("out@example.com")

    response = await join(async_client, team.general_channel_id, outsider)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_a_team_member"


@pytest.mark.parametrize("kind", [Channel.Kind.PRIVATE, Channel.Kind.DM])
async def test_cannot_join_private_or_dm(async_client, team, member, kind):
    channel = await Channel.objects.acreate(team_id=team.id, name="secret", kind=kind)

    response = await join(async_client, channel.id, member)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "cannot_join_private"


async def test_cannot_join_archived_channel(async_client, team, member):
    channel = await Channel.objects.acreate(
        team_id=team.id, name="old", kind=Channel.Kind.PUBLIC, archived_at=timezone.now()
    )

    response = await join(async_client, channel.id, member)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "channel_archived"


async def test_missing_channel_is_404(async_client, member):
    response = await join(async_client, uuid.uuid4(), member)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "channel_not_found"
