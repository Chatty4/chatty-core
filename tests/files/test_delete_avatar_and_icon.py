"""DELETE /files/{file_id} of a file in use: removed from my profile or from the team first."""

import pytest

from files.models import File
from teams.models import Team, TeamMember
from tests.helpers import headers_for, make_file, make_user

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.usefixtures("remove_objects")]


async def delete(client, file_id, headers: dict):
    return await client.delete(f"/api/core/v1/files/{file_id}", headers=headers)


async def set_icon(client, team, file_id, headers: dict) -> None:
    body = {"name": team.name, "icon_file_id": str(file_id)}
    response = await client.put(
        f"/api/core/v1/teams/{team.id}", body, content_type="application/json", headers=headers
    )
    assert response.status_code == 200


async def join(team, role: TeamMember.Role):
    """A new user in the team with this role, and their headers."""
    user = await make_user(f"{role}@example.com")
    await TeamMember.objects.acreate(team=team, user=user, role=role)
    return user, await headers_for(user)


async def test_delete_my_current_avatar(async_client, user, auth):
    file = await make_file(user)
    body = {"display_name": "Ana Pop", "timezone": "UTC", "avatar_file_id": str(file.id)}
    await async_client.put("/api/core/v1/me", body, content_type="application/json", headers=auth)

    response = await delete(async_client, file.id, auth)

    assert response.status_code == 204
    me = await async_client.get("/api/core/v1/me", headers=auth)
    assert me.json()["avatar_file_id"] is None
    assert (await File.objects.aget(id=file.id)).deleted_at is not None


@pytest.mark.parametrize("role", [TeamMember.Role.OWNER, TeamMember.Role.ADMIN])
async def test_manager_deletes_the_team_icon_they_uploaded(async_client, team, role):
    manager, headers = await join(team, role)
    file = await make_file(manager, "team_icon", team)
    await set_icon(async_client, team, file.id, headers)

    response = await delete(async_client, file.id, headers)

    assert response.status_code == 204
    detail = await async_client.get(f"/api/core/v1/teams/{team.id}", headers=headers)
    assert detail.json()["icon_file_id"] is None
    assert (await File.objects.aget(id=file.id)).deleted_at is not None


async def test_member_cant_delete_the_team_icon(async_client, auth, team):
    """A member uploaded it and an owner set it: only an owner or admin may change it."""
    member, headers = await join(team, TeamMember.Role.MEMBER)
    file = await make_file(member, "team_icon", team)
    await set_icon(async_client, team, file.id, auth)

    response = await delete(async_client, file.id, headers)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
    assert (await Team.objects.aget(id=team.id)).icon_id == file.id
    assert (await File.objects.aget(id=file.id)).deleted_at is None


async def test_member_deletes_a_team_icon_no_team_uses(async_client, team):
    member, headers = await join(team, TeamMember.Role.MEMBER)
    file = await make_file(member, "team_icon", team)

    response = await delete(async_client, file.id, headers)

    assert response.status_code == 204
    assert (await File.objects.aget(id=file.id)).deleted_at is not None
