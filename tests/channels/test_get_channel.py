import uuid

import pytest
from asgiref.sync import sync_to_async

from authn.services import AuthnService
from channels.models import Channel
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


async def get_channel(client, channel_id, as_user):
    return await client.get(
        f"/api/core/v1/channels/{channel_id}", headers=await headers_for(as_user)
    )


async def test_channel_member_gets_the_channel_with_their_settings(async_client, owner, team):
    response = await get_channel(async_client, team.general_channel_id, owner)

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(team.general_channel_id)
    assert body["team_id"] == str(team.id)
    assert body["name"] == "general"
    assert body["is_default"] is True
    assert body["member_count"] == 1
    assert body["created_by"] == str(owner.id)
    assert body["my"] == {
        "role": "owner",
        "notify_level": "mentions",
        "muted": False,
        "hidden": False,
    }


async def test_team_member_reads_a_public_channel_they_havent_joined(async_client, team, member):
    response = await get_channel(async_client, team.general_channel_id, member)

    assert response.status_code == 200
    assert response.json()["my"] is None


async def test_private_channel_im_not_in_is_forbidden(async_client, team, member):
    secret = await Channel.objects.acreate(
        team_id=team.id, name="secret", kind=Channel.Kind.PRIVATE
    )

    response = await get_channel(async_client, secret.id, member)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "cannot_read_channel"


async def test_outsider_cannot_read(async_client, team):
    outsider = await make_user("out@example.com")

    response = await get_channel(async_client, team.general_channel_id, outsider)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "cannot_read_channel"


async def test_unknown_channel_is_not_found(async_client, owner):
    response = await get_channel(async_client, uuid.uuid4(), owner)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "channel_not_found"
