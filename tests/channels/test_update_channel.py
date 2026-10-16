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
    """Team owner."""
    return await make_user("owner@example.com")


@pytest.fixture
async def team(owner):
    return await TeamService.create("Backend", owner.id)


@pytest.fixture
async def member(team):
    user = await make_user("member@example.com")
    await TeamMember.objects.acreate(team_id=team.id, user=user, role=TeamMember.Role.MEMBER)
    return user


@pytest.fixture
async def secret(team):
    """Private channel the team owner is not in."""
    return await Channel.objects.acreate(
        team_id=team.id, name="secret", kind=Channel.Kind.PRIVATE, topic="old topic"
    )


async def add_to(channel_id, user, role=ChannelMember.Role.MEMBER) -> ChannelMember:
    return await ChannelMember.objects.acreate(
        channel_id=channel_id, user=user, role=role, notify_level=ChannelMember.NotifyLevel.ALL
    )


async def update(client, channel_id, as_user, body):
    return await client.put(
        f"/api/core/v1/channels/{channel_id}",
        body,
        content_type="application/json",
        headers=await headers_for(as_user),
    )


async def test_channel_owner_renames_and_changes_topic(async_client, member, secret):
    await add_to(secret.id, member, ChannelMember.Role.OWNER)

    response = await update(
        async_client, secret.id, member, {"name": "release-notes", "topic": "Everything that ships"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "release-notes"
    assert body["topic"] == "Everything that ships"
    assert body["member_count"] == 1
    assert body["my"]["role"] == "owner"


async def test_no_topic_keeps_the_current_one(async_client, owner, secret):
    response = await update(async_client, secret.id, owner, {"name": "renamed"})

    assert response.json()["topic"] == "old topic"


async def test_team_owner_renames_channel_they_are_not_in(async_client, owner, secret):
    response = await update(async_client, secret.id, owner, {"name": "renamed"})

    assert response.status_code == 200
    assert response.json()["my"] is None


async def test_plain_member_cannot_rename(async_client, member, secret):
    await add_to(secret.id, member)

    response = await update(async_client, secret.id, member, {"name": "renamed"})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


async def test_name_taken_in_team_is_409(async_client, owner, secret):
    response = await update(async_client, secret.id, owner, {"name": "general"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "channel_name_taken"


async def test_archived_channel_cannot_be_renamed(async_client, team, owner):
    old = await Channel.objects.acreate(
        team_id=team.id, name="old", kind=Channel.Kind.PUBLIC, archived_at=timezone.now()
    )

    response = await update(async_client, old.id, owner, {"name": "renamed"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "channel_archived"


async def test_dm_cannot_be_renamed(async_client, team, owner):
    dm = await Channel.objects.acreate(team_id=team.id, kind=Channel.Kind.DM, dm_key="x")
    await add_to(dm.id, owner)

    response = await update(async_client, dm.id, owner, {"name": "renamed"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "not_allowed_for_dm"


async def test_invalid_name_is_rejected(async_client, owner, secret):
    response = await update(async_client, secret.id, owner, {"name": "Not Valid!"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


async def test_missing_channel_is_404(async_client, owner):
    response = await update(async_client, uuid.uuid4(), owner, {"name": "renamed"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "channel_not_found"
