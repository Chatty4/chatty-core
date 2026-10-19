import pytest

from channels.models import Channel, ChannelMember
from teams.models import TeamMember
from teams.services import TeamService
from tests.helpers import headers_for, make_user

pytestmark = pytest.mark.django_db(transaction=True)

SETTINGS = {"notify_level": "all", "muted": True, "hidden": False}


def url(channel_id):
    return f"/api/core/v1/channels/{channel_id}/me"


@pytest.fixture
async def ana():
    return await make_user("ana@example.com")


@pytest.fixture
async def bob():
    return await make_user("bob@example.com")


@pytest.fixture
async def team(ana, bob):
    created = await TeamService.create("Backend", ana.id)
    await TeamMember.objects.acreate(team_id=created.id, user=bob, role=TeamMember.Role.MEMBER)
    return created


@pytest.fixture
async def general(team):
    return await Channel.objects.aget(id=team.general_channel_id)


@pytest.fixture
async def dm(team, ana, bob):
    channel = await Channel.objects.acreate(
        team_id=team.id, kind=Channel.Kind.DM, dm_key=":".join(sorted([str(ana.id), str(bob.id)]))
    )
    for user in (ana, bob):
        await ChannelMember.objects.acreate(
            channel=channel, user=user, notify_level=ChannelMember.NotifyLevel.ALL
        )
    return channel


async def put(async_client, channel, user, body=SETTINGS):
    return await async_client.put(
        url(channel.id), body, content_type="application/json", headers=await headers_for(user)
    )


# --- success ---


async def test_update_settings_returns_200_and_body(async_client, general, ana):
    response = await put(async_client, general, ana)

    assert response.status_code == 200
    assert response.json() == {
        "channel_id": str(general.id),
        "role": "owner",
        "notify_level": "all",
        "muted": True,
        "hidden": False,
    }


async def test_update_settings_saves_them(async_client, general, ana):
    await put(async_client, general, ana)

    member = await ChannelMember.objects.aget(channel=general, user=ana)
    assert (member.notify_level, member.muted, member.hidden) == ("all", True, False)


async def test_hide_dm(async_client, dm, ana):
    response = await put(async_client, dm, ana, {**SETTINGS, "hidden": True})

    assert response.status_code == 200
    assert response.json()["hidden"] is True


async def test_only_my_membership_changes(async_client, dm, ana, bob):
    await put(async_client, dm, ana, {**SETTINGS, "hidden": True})

    other = await ChannelMember.objects.aget(channel=dm, user=bob)
    assert (other.notify_level, other.muted, other.hidden) == ("all", False, False)


# --- validation ---


async def test_hidden_on_channel_returns_400(async_client, general, ana):
    response = await put(async_client, general, ana, {**SETTINGS, "hidden": True})

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {"hidden": "invalid"}


async def test_unknown_notify_level_returns_400(async_client, general, ana):
    response = await put(async_client, general, ana, {**SETTINGS, "notify_level": "loud"})

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {"notify_level": "invalid_choice"}


async def test_missing_field_returns_400(async_client, general, ana):
    response = await put(async_client, general, ana, {"notify_level": "all", "muted": True})

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {"hidden": "required"}


# --- access ---


async def test_not_a_member_returns_403(async_client, team, ana, bob):
    random = await Channel.objects.acreate(
        team_id=team.id, name="random", kind=Channel.Kind.PUBLIC, created_by=ana
    )

    response = await put(async_client, random, bob)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_a_member"


async def test_unknown_channel_returns_404(async_client, ana):
    class Missing:
        id = "00000000-0000-0000-0000-000000000000"

    response = await put(async_client, Missing, ana)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "channel_not_found"


async def test_requires_auth(async_client, general):
    response = await async_client.put(url(general.id), SETTINGS, content_type="application/json")

    assert response.status_code == 401
