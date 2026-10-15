import uuid

import pytest
from asgiref.sync import sync_to_async

from authn.services import AuthnService
from teams.models import TeamMember
from teams.services import TeamService
from users.models import User

pytestmark = pytest.mark.django_db(transaction=True)

ALL = ["Ana Pop", "Bogdan Mihailescu", "Ioana Marin", "Mihai Ionescu"]


async def make_user(email: str, name: str) -> User:
    return await sync_to_async(User.objects.create_user)(
        email=email, display_name=name, password="correct horse battery"
    )


async def headers_for(user: User) -> dict:
    tokens = await AuthnService().issue_tokens(user)
    return {"Authorization": f"Bearer {tokens.access_token}"}


@pytest.fixture
async def owner():
    return await make_user("owner@example.com", "Ana Pop")


@pytest.fixture
async def auth(owner):
    return await headers_for(owner)


@pytest.fixture
async def team(owner):
    team = await TeamService.create("Backend", owner.id)
    for i, name in enumerate(["Mihai Ionescu", "Ioana Marin", "Bogdan Mihailescu"]):
        user = await make_user(f"u{i}@example.com", name)
        await TeamMember.objects.acreate(team_id=team.id, user=user)
    return team


async def get_members(client, team, headers, **params):
    return await client.get(f"/api/core/v1/teams/{team.id}/members", params, headers=headers)


def names(body: dict) -> list[str]:
    return [m["display_name"] for m in body["members"]]


async def test_returns_every_member_sorted_by_name(async_client, team, auth):
    response = await get_members(async_client, team, auth)

    assert response.status_code == 200
    assert names(response.json()) == ALL
    assert response.json()["next_cursor"] is None


async def test_member_has_the_contract_fields(async_client, owner, team, auth):
    first = (await get_members(async_client, team, auth)).json()["members"][0]

    assert first == {
        "user_id": str(owner.id),
        "display_name": "Ana Pop",
        "avatar_file_id": None,
        "role": "owner",
        "is_active": True,
        "joined_at": first["joined_at"],
    }


async def test_pages_follow_next_cursor(async_client, team, auth):
    page1 = (await get_members(async_client, team, auth, limit=3)).json()
    page2 = (
        await get_members(async_client, team, auth, limit=3, cursor=page1["next_cursor"])
    ).json()

    assert names(page1) + names(page2) == ALL
    assert page2["next_cursor"] is None


async def test_q_matches_the_start_of_any_name_word(async_client, team, auth):
    body = (await get_members(async_client, team, auth, q="mi")).json()

    assert names(body) == ["Bogdan Mihailescu", "Mihai Ionescu"]  # not "Ioana Marin"


async def test_cursor_from_another_q_is_rejected(async_client, team, auth):
    cursor = (await get_members(async_client, team, auth, limit=1)).json()["next_cursor"]

    response = await get_members(async_client, team, auth, q="mi", cursor=cursor)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_cursor"


async def test_limit_out_of_range_is_rejected(async_client, team, auth):
    response = await get_members(async_client, team, auth, limit=0)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


async def test_outsider_gets_403(async_client, team):
    outsider = await make_user("out@example.com", "Out Sider")

    response = await get_members(async_client, team, await headers_for(outsider))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_a_team_member"

async def ids_by_name(team) -> dict[str, str]:
    return {
        m.user.display_name: str(m.user.id)
        async for m in TeamMember.objects.filter(team_id=team.id).select_related("user")
    }


async def test_user_ids_returns_exactly_those_members(async_client, team, auth):
    ids = await ids_by_name(team)
    wanted = f"{ids['Mihai Ionescu']},{ids['Ana Pop']}"

    body = (await get_members(async_client, team, auth, user_ids=wanted)).json()

    assert names(body) == ["Ana Pop", "Mihai Ionescu"]
    assert body["next_cursor"] is None


async def test_user_ids_leaves_out_people_not_in_the_team(async_client, team, auth):
    ids = await ids_by_name(team)
    wanted = f"{ids['Ana Pop']},{uuid.uuid4()}"

    body = (await get_members(async_client, team, auth, user_ids=wanted)).json()

    assert names(body) == ["Ana Pop"]


async def test_more_than_100_user_ids_is_rejected(async_client, team, auth):
    wanted = ",".join(str(uuid.uuid4()) for _ in range(101))

    response = await get_members(async_client, team, auth, user_ids=wanted)

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {"user_ids": "too_many"}


async def test_user_ids_with_cursor_is_rejected(async_client, team, auth):
    ids = await ids_by_name(team)

    response = await get_members(
        async_client, team, auth, user_ids=ids["Ana Pop"], cursor="anything"
    )

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {"user_ids": "not_with_cursor"}


async def test_bad_user_id_is_rejected(async_client, team, auth):
    response = await get_members(async_client, team, auth, user_ids="not-a-uuid")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"