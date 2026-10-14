import pytest
from asgiref.sync import sync_to_async

from authn.services import AuthnService
from teams.models import Team, TeamMember
from users.models import User

pytestmark = pytest.mark.django_db(transaction=True)

URL = "/api/core/v1/teams"


@pytest.fixture
async def user():
    return await sync_to_async(User.objects.create_user)(
        email="ana@example.com", display_name="Ana Pop", password="correct horse battery"
    )


@pytest.fixture
async def auth(user):
    tokens = await AuthnService().issue_tokens(user)
    return {"Authorization": f"Bearer {tokens.access_token}"}


async def get_teams(client, headers):
    return await client.get(URL, headers=headers)


async def make_team(name: str, owner: User) -> Team:
    team = await Team.objects.acreate(name=name, created_by=owner)
    await TeamMember.objects.acreate(team=team, user=owner, role=TeamMember.Role.OWNER)
    return team


async def test_get_teams_returns_200(async_client, user, auth):
    response = await get_teams(async_client, auth)

    assert response.status_code == 200
    assert "teams" in response.json()


async def test_get_teams_empty_for_new_user(async_client, user, auth):
    response = await get_teams(async_client, auth)

    assert response.status_code == 200
    assert response.json()["teams"] == []


async def test_get_teams_returns_own_team(async_client, user, auth):
    team = await make_team("Backend", user)

    response = await get_teams(async_client, auth)

    assert response.status_code == 200
    teams = response.json()["teams"]
    assert len(teams) == 1
    assert teams[0]["id"] == str(team.id)
    assert teams[0]["name"] == "Backend"
    assert teams[0]["icon_file_id"] is None
    assert teams[0]["role"] == "owner"
    assert teams[0]["member_count"] == 1
    assert teams[0]["created_at"]


async def test_get_teams_member_count_reflects_all_members(async_client, user, auth):
    team = await make_team("Backend", user)
    other = await sync_to_async(User.objects.create_user)(
        email="other@example.com", display_name="Other", password="correct horse battery"
    )
    await TeamMember.objects.acreate(team=team, user=other, role=TeamMember.Role.MEMBER)

    response = await get_teams(async_client, auth)

    assert response.json()["teams"][0]["member_count"] == 2


async def test_get_teams_role_reflects_user_role(async_client, user, auth):
    other = await sync_to_async(User.objects.create_user)(
        email="other@example.com", display_name="Other", password="correct horse battery"
    )
    team = await make_team("Backend", other)
    await TeamMember.objects.acreate(team=team, user=user, role=TeamMember.Role.MEMBER)

    response = await get_teams(async_client, auth)

    assert response.json()["teams"][0]["role"] == "member"


async def test_get_teams_excludes_teams_user_not_member_of(async_client, user, auth):
    other = await sync_to_async(User.objects.create_user)(
        email="other@example.com", display_name="Other", password="correct horse battery"
    )
    await make_team("Other's Team", other)

    response = await get_teams(async_client, auth)

    assert response.json()["teams"] == []


async def test_get_teams_excludes_deleted_teams(async_client, user, auth):
    from django.utils import timezone

    team = await make_team("Deleted", user)
    team.deleted_at = timezone.now()
    await team.asave(update_fields=["deleted_at"])

    response = await get_teams(async_client, auth)

    assert response.json()["teams"] == []


async def test_get_teams_requires_auth(async_client):
    response = await get_teams(async_client, {})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_get_teams_inactive_user(async_client, user, auth):
    user.is_active = False
    await user.asave(update_fields=["is_active"])

    response = await get_teams(async_client, auth)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "user_inactive"


async def test_get_teams_returns_multiple_teams_ordered_by_created_at(async_client, user, auth):
    team1 = await make_team("Alpha", user)
    team2 = await make_team("Beta", user)
    team3 = await make_team("Gamma", user)

    response = await get_teams(async_client, auth)

    ids = [t["id"] for t in response.json()["teams"]]
    assert ids == [str(team1.id), str(team2.id), str(team3.id)]
