import pytest

from channels.models import Channel, ChannelMember
from teams.services import TeamService
from tests.helpers import headers_for, make_user

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
async def owner():
    return await make_user("owner@example.com")


@pytest.fixture
async def team(owner):
    return await TeamService.create("Backend", owner.id)


async def create(client, team, body, as_user):
    return await client.post(
        f"/api/core/v1/teams/{team.id}/channels",
        body,
        content_type="application/json",
        headers=await headers_for(as_user),
    )


async def test_creates_a_channel(async_client, owner, team):
    body = {"name": "releases", "kind": "public", "topic": "Release notes"}

    response = await create(async_client, team, body, owner)

    assert response.status_code == 201
    data = response.json()
    assert data["team_id"] == str(team.id)
    assert data["name"] == "releases"
    assert data["kind"] == "public"
    assert data["topic"] == "Release notes"
    assert data["is_default"] is False
    assert data["archived"] is False
    assert data["created_by"] == str(owner.id)


async def test_creator_is_the_owner_and_only_member(async_client, owner, team):
    data = (await create(async_client, team, {"name": "secret", "kind": "private"}, owner)).json()

    members = [m async for m in ChannelMember.objects.filter(channel_id=data["id"])]
    assert len(members) == 1
    assert members[0].user_id == owner.id  # type: ignore
    assert members[0].role == ChannelMember.Role.OWNER
    assert members[0].notify_level == ChannelMember.NotifyLevel.MENTIONS


async def test_topic_is_optional(async_client, owner, team):
    data = (await create(async_client, team, {"name": "random", "kind": "public"}, owner)).json()

    assert data["topic"] == ""


@pytest.mark.parametrize("name", ["general", "releases"])
async def test_name_taken_in_the_team_is_a_conflict(async_client, owner, team, name):
    await create(async_client, team, {"name": "releases", "kind": "public"}, owner)

    response = await create(async_client, team, {"name": name, "kind": "private"}, owner)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "channel_name_taken"


async def test_same_name_in_another_team_is_fine(async_client, owner, team):
    other = await TeamService.create("Frontend", owner.id)
    await create(async_client, team, {"name": "releases", "kind": "public"}, owner)

    response = await create(async_client, other, {"name": "releases", "kind": "public"}, owner)

    assert response.status_code == 201


@pytest.mark.parametrize(
    "body",
    [
        {"name": "Releases", "kind": "public"},  # uppercase
        {"name": "has space", "kind": "public"},
        {"name": "", "kind": "public"},
        {"name": "a" * 81, "kind": "public"},
        {"name": "releases", "kind": "dm"},
        {"name": "releases", "kind": "public", "topic": "t" * 251},
    ],
)
async def test_invalid_body_is_rejected(async_client, owner, team, body):
    response = await create(async_client, team, body, owner)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


async def test_outsider_gets_403(async_client, team):
    outsider = await make_user("out@example.com")

    response = await create(async_client, team, {"name": "releases", "kind": "public"}, outsider)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_a_team_member"
    assert not await Channel.objects.filter(name="releases").aexists()
