import uuid
from datetime import timedelta

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
    return await Channel.objects.acreate(team_id=team.id, name="secret", kind=Channel.Kind.PRIVATE)


async def add_to(channel_id, user, role=ChannelMember.Role.MEMBER) -> ChannelMember:
    return await ChannelMember.objects.acreate(
        channel_id=channel_id, user=user, role=role, notify_level=ChannelMember.NotifyLevel.ALL
    )


async def archive(client, channel_id, as_user):
    return await client.post(
        f"/api/core/v1/channels/{channel_id}/archive", headers=await headers_for(as_user)
    )


async def test_channel_owner_archives(async_client, member, secret):
    await add_to(secret.id, member, ChannelMember.Role.OWNER)

    response = await archive(async_client, secret.id, member)

    assert response.status_code == 200
    body = response.json()
    assert body["archived"] is True
    assert body["member_count"] == 1
    await secret.arefresh_from_db()
    assert secret.archived_at is not None


async def test_archiving_twice_returns_200_and_keeps_the_first_time(async_client, owner, secret):
    first = timezone.now() - timedelta(days=1)
    await Channel.objects.filter(pk=secret.pk).aupdate(archived_at=first)

    response = await archive(async_client, secret.id, owner)

    assert response.status_code == 200
    assert response.json()["archived"] is True
    await secret.arefresh_from_db()
    assert secret.archived_at == first


async def test_team_owner_archives_channel_they_are_not_in(async_client, owner, secret):
    response = await archive(async_client, secret.id, owner)

    assert response.status_code == 200
    assert response.json()["my"] is None


async def test_default_channel_cannot_be_archived(async_client, team, owner):
    response = await archive(async_client, team.general_channel_id, owner)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "cannot_archive_default"


async def test_plain_member_cannot_archive(async_client, member, secret):
    await add_to(secret.id, member)

    response = await archive(async_client, secret.id, member)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


async def test_dm_cannot_be_archived(async_client, team, owner):
    dm = await Channel.objects.acreate(team_id=team.id, kind=Channel.Kind.DM, dm_key="x")
    await add_to(dm.id, owner)

    response = await archive(async_client, dm.id, owner)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "not_allowed_for_dm"


async def test_missing_channel_is_404(async_client, owner):
    response = await archive(async_client, uuid.uuid4(), owner)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "channel_not_found"
