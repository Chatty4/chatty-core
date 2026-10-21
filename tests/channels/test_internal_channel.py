import pytest
from django.conf import settings
from django.utils import timezone

from channels.models import Channel, ChannelMember
from channels.services import ChannelService
from teams.models import Team, TeamMember
from teams.services import TeamService
from tests.helpers import make_user

pytestmark = pytest.mark.django_db(transaction=True)

SERVICE = {"X-Service-Token": settings.CORE_SERVICE_TOKEN}


def url(channel_id):
    return f"/internal/channels/{channel_id}"


async def get(async_client, channel_id, headers=SERVICE):
    return await async_client.get(url(channel_id), headers=headers)


@pytest.fixture
async def world():
    """Ana owns team A and private "secret", where Bob is a member; Ana and Bob have a DM."""
    ana, bob = await make_user("ana@example.com"), await make_user("bob@example.com")
    team = await TeamService.create("A", ana.id)
    await TeamMember.objects.acreate(team_id=team.id, user=bob, role=TeamMember.Role.MEMBER)
    secret = await Channel.objects.acreate(
        team_id=team.id, name="secret", kind=Channel.Kind.PRIVATE
    )
    await ChannelMember.objects.acreate(
        channel=secret,
        user=ana,
        role=ChannelMember.Role.OWNER,
        notify_level=ChannelMember.NotifyLevel.ALL,
    )
    await ChannelMember.objects.acreate(
        channel=secret,
        user=bob,
        notify_level=ChannelMember.NotifyLevel.MENTIONS,
        muted=True,
    )
    dm = await ChannelService.open_dm(team.id, ana.id, [bob.id])
    return {"ana": ana, "bob": bob, "team": team, "secret": secret, "dm": dm.channel}


# --- auth ---


async def test_requires_service_token(async_client, world):
    response = await get(async_client, world["secret"].id, headers={})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_service_token"


async def test_wrong_service_token(async_client, world):
    response = await get(async_client, world["secret"].id, headers={"X-Service-Token": "wrong"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_service_token"


# --- body ---


async def test_unknown_channel_returns_404(async_client):
    response = await get(async_client, "00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "channel_not_found"


async def test_private_channel_with_members_and_settings(async_client, world):
    response = await get(async_client, world["secret"].id)

    assert response.status_code == 200
    body = response.json()
    assert {k: body[k] for k in ("channel_id", "team_id", "kind", "archived", "team_deleted")} == {
        "channel_id": str(world["secret"].id),
        "team_id": str(world["team"].id),
        "kind": "private",
        "archived": False,
        "team_deleted": False,
    }
    members = {m["user_id"]: m for m in body["members"]}
    assert members == {
        str(world["ana"].id): {
            "user_id": str(world["ana"].id),
            "role": "owner",
            "notify_level": "all",
            "muted": False,
        },
        str(world["bob"].id): {
            "user_id": str(world["bob"].id),
            "role": "member",
            "notify_level": "mentions",
            "muted": True,
        },
    }


async def test_dm_members_are_members_with_notify_all(async_client, world):
    body = (await get(async_client, world["dm"].id)).json()

    assert body["kind"] == "dm"
    assert len(body["members"]) == 2
    assert {(m["role"], m["notify_level"]) for m in body["members"]} == {("member", "all")}


async def test_archived_channel(async_client, world):
    await Channel.objects.filter(id=world["secret"].id).aupdate(archived_at=timezone.now())

    body = (await get(async_client, world["secret"].id)).json()

    assert body["archived"] is True


async def test_channel_of_deleted_team_returns_200(async_client, world):
    await Team.objects.filter(id=world["team"].id).aupdate(deleted_at=timezone.now())

    response = await get(async_client, world["secret"].id)

    assert response.status_code == 200
    assert response.json()["team_deleted"] is True
