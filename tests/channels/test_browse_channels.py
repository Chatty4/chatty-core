import pytest
from asgiref.sync import sync_to_async

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


async def channel(team, name: str, kind=Channel.Kind.PUBLIC) -> Channel:
    return await Channel.objects.acreate(team_id=team.id, name=name, kind=kind)


async def join(channel_id, user) -> None:
    await ChannelMember.objects.acreate(
        channel_id=channel_id,
        user=user,
        role=ChannelMember.Role.MEMBER,
        notify_level=ChannelMember.NotifyLevel.MENTIONS,
    )


@pytest.fixture
async def owner():
    return await make_user("owner@example.com")


@pytest.fixture
async def team(owner):
    return await TeamService.create("Backend", owner.id)


@pytest.fixture
async def member(team):
    """In the team, not in any channel yet."""
    user = await make_user("member@example.com")
    await TeamMember.objects.acreate(team_id=team.id, user=user, role=TeamMember.Role.MEMBER)
    return user


async def browse(client, team, as_user, **params):
    return await client.get(
        f"/api/core/v1/teams/{team.id}/channels/browse", params, headers=await headers_for(as_user)
    )


def names(body: dict) -> list[str]:
    return [c["name"] for c in body["channels"]]


async def test_lists_public_channels_i_havent_joined(async_client, team, member):
    await channel(team, "releases")
    await channel(team, "secret", kind=Channel.Kind.PRIVATE)

    response = await browse(async_client, team, member)

    assert response.status_code == 200
    assert names(response.json()) == ["general", "releases"]  # A to Z, no private
    assert response.json()["next_cursor"] is None


async def test_channels_i_joined_are_left_out(async_client, owner, team):
    await channel(team, "releases")

    body = (await browse(async_client, team, owner)).json()

    assert names(body) == ["releases"]  # the owner is already in general


async def test_item_has_the_contract_fields(async_client, owner, team, member):
    releases = await channel(team, "releases")
    await join(releases.id, owner)

    item = (await browse(async_client, team, member)).json()["channels"][1]

    assert item == {
        "id": str(releases.id),
        "name": "releases",
        "topic": "",
        "member_count": 1,
        "archived": False,
    }


async def test_q_matches_the_channel_name(async_client, team, member):
    for name in ["releases", "dev-releases", "random"]:
        await channel(team, name)

    body = (await browse(async_client, team, member, q="rel")).json()

    assert names(body) == ["dev-releases", "releases"]


async def test_pages_follow_next_cursor(async_client, team, member):
    for name in ["alpha", "beta"]:
        await channel(team, name)

    page1 = (await browse(async_client, team, member, limit=2)).json()
    page2 = (await browse(async_client, team, member, limit=2, cursor=page1["next_cursor"])).json()

    assert names(page1) + names(page2) == ["alpha", "beta", "general"]
    assert page2["next_cursor"] is None


async def test_outsider_gets_403(async_client, team):
    outsider = await make_user("out@example.com")

    response = await browse(async_client, team, outsider)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_a_team_member"