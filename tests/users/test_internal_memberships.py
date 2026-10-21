import pytest
from django.conf import settings
from django.db.backends import utils
from django.utils import timezone

from channels.models import Channel, ChannelMember
from channels.services import ChannelService
from teams.models import Team, TeamMember
from teams.services import TeamService
from tests.helpers import headers_for, make_user
from users.services import UserService

pytestmark = pytest.mark.django_db(transaction=True)

SERVICE = {"X-Service-Token": settings.CORE_SERVICE_TOKEN}


def url(user_id):
    return f"/internal/users/{user_id}/memberships"


@pytest.fixture
async def world():
    """Ana owns team A (general, an unjoined public "random", private "secret") and is an admin
    in Olga's team B, where she has a DM with Olga."""
    ana, olga = await make_user("ana@example.com"), await make_user("olga@example.com")
    team_a = await TeamService.create("A", ana.id)
    team_b = await TeamService.create("B", olga.id)
    await TeamMember.objects.acreate(team_id=team_b.id, user=ana, role=TeamMember.Role.ADMIN)
    random = await Channel.objects.acreate(
        team_id=team_a.id, name="random", kind=Channel.Kind.PUBLIC
    )
    secret = await Channel.objects.acreate(
        team_id=team_a.id, name="secret", kind=Channel.Kind.PRIVATE
    )
    await ChannelMember.objects.acreate(
        channel=secret,
        user=ana,
        role=ChannelMember.Role.OWNER,
        notify_level=ChannelMember.NotifyLevel.ALL,
    )
    dm = await ChannelService.open_dm(team_b.id, ana.id, [olga.id])
    return {
        "ana": ana,
        "a": team_a,
        "b": team_b,
        "random": random,
        "secret": secret,
        "dm": dm.channel,
    }


async def get(async_client, user_id, headers=SERVICE):
    return await async_client.get(url(user_id), headers=headers)


# --- auth ---


async def test_requires_service_token(async_client, world):
    response = await get(async_client, world["ana"].id, headers={})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_service_token"


async def test_wrong_service_token(async_client, world):
    response = await get(async_client, world["ana"].id, headers={"X-Service-Token": "wrong"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_service_token"


async def test_user_jwt_is_not_enough(async_client, world):
    response = await get(async_client, world["ana"].id, headers=await headers_for(world["ana"]))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_service_token"


# --- body ---


async def test_unknown_user_returns_404(async_client):
    response = await get(async_client, "00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "user_not_found"


async def test_teams_with_role_and_all_public_channels(async_client, world):
    response = await get(async_client, world["ana"].id)

    assert response.status_code == 200
    body = response.json()
    teams = {t["team_id"]: t for t in body["teams"]}
    assert body["user_id"] == str(world["ana"].id)
    assert body["is_active"] is True
    assert teams[str(world["a"].id)]["role"] == "owner"
    assert teams[str(world["b"].id)]["role"] == "admin"
    assert set(teams[str(world["a"].id)]["public_channel_ids"]) == {
        str(world["a"].general_channel_id),
        str(world["random"].id),  # public but not joined
    }


async def test_channels_are_only_mine_with_settings(async_client, world):
    body = (await get(async_client, world["ana"].id)).json()

    channels = {c["channel_id"]: c for c in body["channels"]}
    assert set(channels) == {
        str(world["a"].general_channel_id),
        str(world["secret"].id),
        str(world["dm"].id),
    }
    assert channels[str(world["secret"].id)] == {
        "channel_id": str(world["secret"].id),
        "team_id": str(world["a"].id),
        "kind": "private",
        "archived": False,
        "role": "owner",
        "notify_level": "all",
        "muted": False,
        "hidden": False,
    }
    assert channels[str(world["dm"].id)]["kind"] == "dm"


async def test_archived_public_channel_is_still_listed(async_client, world):
    general_id = world["a"].general_channel_id
    await Channel.objects.filter(id=general_id).aupdate(archived_at=timezone.now())

    body = (await get(async_client, world["ana"].id)).json()

    team_a = next(t for t in body["teams"] if t["team_id"] == str(world["a"].id))
    general = next(c for c in body["channels"] if c["channel_id"] == str(general_id))
    assert str(general_id) in team_a["public_channel_ids"]
    assert general["archived"] is True


async def test_deleted_team_and_its_channels_are_left_out(async_client, world):
    await Team.objects.filter(id=world["b"].id).aupdate(deleted_at=timezone.now())

    body = (await get(async_client, world["ana"].id)).json()

    assert [t["team_id"] for t in body["teams"]] == [str(world["a"].id)]
    assert str(world["dm"].id) not in {c["channel_id"] for c in body["channels"]}


async def test_leftover_channel_row_outside_my_teams_is_left_out(async_client, world):
    # a channel row in a team I'm not in (e.g. left over from a race with my removal)
    olga_only = await Channel.objects.acreate(
        team_id=world["b"].id, name="olga-only", kind=Channel.Kind.PRIVATE
    )
    await TeamMember.objects.filter(team_id=world["b"].id, user=world["ana"]).adelete()
    await ChannelMember.objects.acreate(
        channel=olga_only, user=world["ana"], notify_level=ChannelMember.NotifyLevel.ALL
    )

    body = (await get(async_client, world["ana"].id)).json()

    assert str(olga_only.id) not in {c["channel_id"] for c in body["channels"]}


async def test_deactivated_user_returns_200(async_client, world):
    world["ana"].is_active = False
    await world["ana"].asave(update_fields=["is_active"])

    response = await get(async_client, world["ana"].id)

    assert response.status_code == 200
    assert response.json()["is_active"] is False


# --- query count ---


@pytest.fixture
def queries(monkeypatch):
    """Every SQL statement, from any thread (the async ORM runs queries in a worker thread)."""
    seen = []
    original = utils.CursorWrapper.execute

    def counting(self, sql, params=None):
        seen.append(sql)
        return original(self, sql, params)

    monkeypatch.setattr(utils.CursorWrapper, "execute", counting)
    return seen


async def test_query_count_does_not_grow_with_teams(queries):
    one, five = await make_user("one@example.com"), await make_user("five@example.com")
    await TeamService.create("solo", one.id)
    for i in range(5):
        await TeamService.create(f"team{i}", five.id)

    queries.clear()
    await UserService.get_memberships(one.id)
    with_one = len(queries)
    queries.clear()
    await UserService.get_memberships(five.id)

    assert len(queries) == with_one == 4
