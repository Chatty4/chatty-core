"""PUT /me with avatar_file_id and PUT /teams/{team_id} with icon_file_id: only a ready file of
the right purpose, mine for an avatar and of this team for an icon (files/access.py)."""

import uuid

import pytest
from django.utils import timezone

from files.models import File
from teams.models import Team
from tests.helpers import make_file, make_user
from users.models import User

pytestmark = pytest.mark.django_db(transaction=True)

ME = "/api/core/v1/me"


async def put_me(client, avatar_file_id, headers: dict, display_name: str = "Ana P."):
    body = {"display_name": display_name, "timezone": "UTC", "avatar_file_id": avatar_file_id}
    return await client.put(ME, body, content_type="application/json", headers=headers)


async def put_team(client, team, icon_file_id, headers: dict, name: str = "Backend team"):
    body = {"name": name, "icon_file_id": icon_file_id}
    return await client.put(
        f"/api/core/v1/teams/{team.id}", body, content_type="application/json", headers=headers
    )


async def assert_invalid_file(response) -> None:
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_file"


# --- PUT /me ---


async def test_set_my_avatar(async_client, user, auth):
    file = await make_file(user)

    response = await put_me(async_client, str(file.id), auth)

    assert response.status_code == 200
    assert response.json()["avatar_file_id"] == str(file.id)
    me = await async_client.get(ME, headers=auth)
    assert me.json()["avatar_file_id"] == str(file.id)


async def not_an_avatar_of_mine(kind: str, user: User, team: Team) -> str:
    if kind == "unknown":
        return str(uuid.uuid4())
    file = {
        "someone_else": make_file_of_bob,
        "pending": lambda: make_file(user, status=File.Status.PENDING),
        "deleted": lambda: make_file(user, deleted_at=timezone.now()),
        "team_icon": lambda: make_file(user, "team_icon", team),
        "attachment": lambda: make_file(user, "attachment", team),
    }[kind]
    return str((await file()).id)


async def make_file_of_bob() -> File:
    return await make_file(await make_user("bob@example.com"))


@pytest.mark.parametrize(
    "kind", ["someone_else", "pending", "deleted", "team_icon", "attachment", "unknown"]
)
async def test_avatar_must_be_a_ready_avatar_of_mine(async_client, user, auth, team, kind):
    current = await make_file(user)
    await put_me(async_client, str(current.id), auth)

    response = await put_me(
        async_client, await not_an_avatar_of_mine(kind, user, team), auth, "Changed"
    )

    await assert_invalid_file(response)
    saved = await User.objects.aget(id=user.id)
    assert saved.avatar_id == current.id
    assert saved.display_name == "Ana P."  # nothing of the PUT was saved


async def test_null_removes_my_avatar(async_client, user, auth):
    file = await make_file(user)
    await put_me(async_client, str(file.id), auth)

    response = await put_me(async_client, None, auth)

    assert response.status_code == 200
    assert response.json()["avatar_file_id"] is None
    assert (await User.objects.aget(id=user.id)).avatar_id is None


# --- PUT /teams/{team_id} ---


async def test_set_the_team_icon(async_client, user, auth, team):
    file = await make_file(user, "team_icon", team)

    response = await put_team(async_client, team, str(file.id), auth)

    assert response.status_code == 200
    assert response.json()["icon_file_id"] == str(file.id)
    detail = await async_client.get(f"/api/core/v1/teams/{team.id}", headers=auth)
    assert detail.json()["icon_file_id"] == str(file.id)


async def not_an_icon_of_this_team(kind: str, user: User, team: Team) -> str:
    if kind == "unknown":
        return str(uuid.uuid4())
    if kind == "other_team":
        other = await Team.objects.acreate(name="Design", created_by=user)
        return str((await make_file(user, "team_icon", other)).id)
    file = {
        "avatar": lambda: make_file(user),
        "pending": lambda: make_file(user, "team_icon", team, status=File.Status.PENDING),
        "deleted": lambda: make_file(user, "team_icon", team, deleted_at=timezone.now()),
    }[kind]
    return str((await file()).id)


@pytest.mark.parametrize("kind", ["other_team", "avatar", "pending", "deleted", "unknown"])
async def test_icon_must_be_a_ready_icon_of_this_team(async_client, user, auth, team, kind):
    current = await make_file(user, "team_icon", team)
    await put_team(async_client, team, str(current.id), auth, "Backend")

    response = await put_team(
        async_client, team, await not_an_icon_of_this_team(kind, user, team), auth, "Changed"
    )

    await assert_invalid_file(response)
    saved = await Team.objects.aget(id=team.id)
    assert saved.icon_id == current.id
    assert saved.name == "Backend"  # nothing of the PUT was saved


async def test_null_removes_the_team_icon(async_client, user, auth, team):
    file = await make_file(user, "team_icon", team)
    await put_team(async_client, team, str(file.id), auth)

    response = await put_team(async_client, team, None, auth)

    assert response.status_code == 200
    assert response.json()["icon_file_id"] is None
    assert (await Team.objects.aget(id=team.id)).icon_id is None
