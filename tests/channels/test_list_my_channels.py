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


async def join(channel_id, user, **settings) -> None:
    await ChannelMember.objects.acreate(
        channel_id=channel_id,
        user=user,
        role=ChannelMember.Role.MEMBER,
        notify_level=settings.pop("notify_level", ChannelMember.NotifyLevel.MENTIONS),
        **settings,
    )


@pytest.fixture
async def owner():
    return await make_user("owner@example.com")


@pytest.fixture
async def team(owner):
    return await TeamService.create("Backend", owner.id)


@pytest.fixture
async def member(team):
    user = await make_user("member@example.com")
    await TeamMember.objects.acreate(team_id=team.id, user=user, role=TeamMember.Role.MEMBER)
    return user


async def my_channels(client, team, as_user):
    return await client.get(
        f"/api/core/v1/teams/{team.id}/channels", headers=await headers_for(as_user)
    )


async def test_owner_sees_general_with_their_settings(async_client, owner, team):
    response = await my_channels(async_client, team, owner)

    assert response.status_code == 200
    assert response.json()["channels"] == [
        {
            "id": str(team.general_channel_id),
            "kind": "public",
            "name": "general",
            "topic": "",
            "is_default": True,
            "archived": False,
            "dm_member_ids": None,
            "my": {"role": "owner", "notify_level": "mentions", "muted": False, "hidden": False},
        }
    ]


async def test_only_channels_im_in(async_client, owner, team, member):
    await Channel.objects.acreate(team_id=team.id, name="secret", kind=Channel.Kind.PRIVATE)

    body = (await my_channels(async_client, team, member)).json()

    assert body["channels"] == []  # not in general, not in secret


async def test_dm_has_no_name_and_lists_its_members(async_client, owner, team, member):
    dm = await Channel.objects.acreate(team_id=team.id, kind=Channel.Kind.DM, dm_key="k")
    await join(dm.id, owner, notify_level=ChannelMember.NotifyLevel.ALL)
    await join(dm.id, member, notify_level=ChannelMember.NotifyLevel.ALL)

    channels = (await my_channels(async_client, team, member)).json()["channels"]

    assert len(channels) == 1
    assert channels[0]["kind"] == "dm"
    assert channels[0]["name"] is None
    assert channels[0]["topic"] is None
    assert channels[0]["dm_member_ids"] == [str(owner.id), str(member.id)]


async def test_hidden_dm_is_still_listed(async_client, owner, team, member):
    dm = await Channel.objects.acreate(team_id=team.id, kind=Channel.Kind.DM, dm_key="k")
    await join(dm.id, member, hidden=True)

    channels = (await my_channels(async_client, team, member)).json()["channels"]

    assert channels[0]["my"]["hidden"] is True


async def test_other_teams_channels_are_left_out(async_client, owner, team):
    await TeamService.create("Frontend", owner.id)  # owner is in its general too

    channels = (await my_channels(async_client, team, owner)).json()["channels"]

    assert [c["id"] for c in channels] == [str(team.general_channel_id)]


async def test_outsider_gets_403(async_client, team):
    outsider = await make_user("out@example.com")

    response = await my_channels(async_client, team, outsider)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_a_team_member"