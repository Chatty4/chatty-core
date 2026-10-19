import pytest

from channels.models import Channel, ChannelMember
from channels.repositories import ChannelRepository
from teams.models import TeamMember
from teams.services import TeamService
from tests.helpers import headers_for, make_user

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
async def users():
    return {n: await make_user(f"{n}@example.com") for n in ("ana", "bob", "carl", "dan")}


@pytest.fixture
async def team(users):
    created = await TeamService.create("Backend", users["ana"].id)
    for name in ("bob", "carl"):
        await TeamMember.objects.acreate(
            team_id=created.id, user=users[name], role=TeamMember.Role.MEMBER
        )
    return created


def url(team_id):
    return f"/api/core/v1/teams/{team_id}/dms"


async def open_dm(async_client, team, me, others):
    return await async_client.post(
        url(team.id),
        {"user_ids": [str(u.id) for u in others]},
        content_type="application/json",
        headers=await headers_for(me),
    )


# --- create ---


async def test_open_dm_returns_201_and_body(async_client, team, users):
    response = await open_dm(async_client, team, users["ana"], [users["bob"]])

    assert response.status_code == 201
    body = response.json()
    assert body["team_id"] == str(team.id)
    assert body["kind"] == "dm"
    assert set(body["member_ids"]) == {str(users["ana"].id), str(users["bob"].id)}
    assert body["created_at"]


async def test_open_dm_members_get_notify_all(async_client, team, users):
    body = (await open_dm(async_client, team, users["ana"], [users["bob"]])).json()

    members = [m async for m in ChannelMember.objects.filter(channel_id=body["id"])]
    assert {(m.role, m.notify_level) for m in members} == {("member", "all")}
    assert len(members) == 2


async def test_open_group_dm(async_client, team, users):
    response = await open_dm(async_client, team, users["ana"], [users["bob"], users["carl"]])

    assert response.status_code == 201
    assert len(response.json()["member_ids"]) == 3


# --- existing DM ---


async def test_open_same_dm_again_returns_200_and_same_id(async_client, team, users):
    first = (await open_dm(async_client, team, users["ana"], [users["bob"]])).json()

    response = await open_dm(async_client, team, users["bob"], [users["ana"]])

    assert response.status_code == 200
    assert response.json()["id"] == first["id"]
    assert await Channel.objects.filter(kind=Channel.Kind.DM).acount() == 1


async def test_duplicates_and_my_own_id_are_ignored(async_client, team, users):
    response = await open_dm(
        async_client, team, users["ana"], [users["bob"], users["bob"], users["ana"]]
    )

    assert response.status_code == 201
    assert len(response.json()["member_ids"]) == 2


async def test_member_who_left_and_rejoined_gets_dm_back(async_client, team, users):
    first = (await open_dm(async_client, team, users["ana"], [users["bob"]])).json()
    await TeamService.leave(team.id, users["bob"].id)
    await TeamMember.objects.acreate(team_id=team.id, user=users["bob"], role="member")

    response = await open_dm(async_client, team, users["ana"], [users["bob"]])

    assert response.status_code == 200
    assert response.json()["id"] == first["id"]
    assert str(users["bob"].id) in response.json()["member_ids"]


async def test_dm_opened_at_the_same_time_returns_existing(async_client, team, users, monkeypatch):
    first = (await open_dm(async_client, team, users["ana"], [users["bob"]])).json()
    original = ChannelRepository.find_dm
    calls = []

    async def first_lookup_misses(team_id, dm_key):  # as if the other request committed after it
        calls.append(dm_key)
        return None if len(calls) == 1 else await original(team_id, dm_key)

    monkeypatch.setattr(ChannelRepository, "find_dm", staticmethod(first_lookup_misses))
    response = await open_dm(async_client, team, users["bob"], [users["ana"]])

    assert response.status_code == 200
    assert response.json()["id"] == first["id"]


# --- errors ---


async def test_only_me_returns_400(async_client, team, users):
    response = await open_dm(async_client, team, users["ana"], [users["ana"]])

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {"user_ids": "invalid"}


async def test_more_than_7_others_returns_400(async_client, team, users):
    others = [await make_user(f"u{i}@example.com") for i in range(8)]
    for user in others:
        await TeamMember.objects.acreate(team_id=team.id, user=user, role="member")

    response = await open_dm(async_client, team, users["ana"], others)

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {"user_ids": "invalid"}


async def test_user_not_in_team_returns_400(async_client, team, users):
    response = await open_dm(async_client, team, users["ana"], [users["dan"]])

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "user_not_in_team"


async def test_not_a_team_member_returns_403(async_client, team, users):
    response = await open_dm(async_client, team, users["dan"], [users["ana"]])

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_a_team_member"


async def test_requires_auth(async_client, team, users):
    response = await async_client.post(
        url(team.id), {"user_ids": [str(users["bob"].id)]}, content_type="application/json"
    )

    assert response.status_code == 401
