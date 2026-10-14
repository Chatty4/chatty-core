import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from authn.services import AuthnService
from teams.models import Team, TeamMember
from users.models import User

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
async def user():
    return await sync_to_async(User.objects.create_user)(
        email="ana@example.com", display_name="Ana Pop", password="correct horse battery"
    )


@pytest.fixture
async def auth(user):
    tokens = await AuthnService().issue_tokens(user)
    return {"Authorization": f"Bearer {tokens.access_token}"}


@pytest.fixture
async def team(user):
    t = await Team.objects.acreate(name="Backend", created_by=user)
    await TeamMember.objects.acreate(team=t, user=user, role=TeamMember.Role.OWNER)
    return t


def url(team_id):
    return f"/api/core/v1/teams/{team_id}"


async def test_get_team_returns_200(async_client, team, auth):
    response = await async_client.get(url(team.id), headers=auth)

    assert response.status_code == 200


async def test_get_team_returns_correct_fields(async_client, user, team, auth):
    response = await async_client.get(url(team.id), headers=auth)

    body = response.json()
    assert body["id"] == str(team.id)
    assert body["name"] == "Backend"
    assert body["icon_file_id"] is None
    assert body["role"] == "owner"
    assert body["member_count"] == 1
    assert body["created_at"]


async def test_get_team_member_count_reflects_all_members(async_client, team, auth):
    other = await sync_to_async(User.objects.create_user)(
        email="other@example.com", display_name="Other", password="correct horse battery"
    )
    await TeamMember.objects.acreate(team=team, user=other, role=TeamMember.Role.MEMBER)

    response = await async_client.get(url(team.id), headers=auth)

    assert response.json()["member_count"] == 2


async def test_get_team_role_reflects_user_role(async_client, team, auth):
    other = await sync_to_async(User.objects.create_user)(
        email="other@example.com", display_name="Other", password="correct horse battery"
    )
    other_tokens = await AuthnService().issue_tokens(other)
    other_auth = {"Authorization": f"Bearer {other_tokens.access_token}"}
    await TeamMember.objects.acreate(team=team, user=other, role=TeamMember.Role.MEMBER)

    response = await async_client.get(url(team.id), headers=other_auth)

    assert response.json()["role"] == "member"


async def test_get_team_not_found(async_client, auth):
    response = await async_client.get(url("00000000-0000-0000-0000-000000000000"), headers=auth)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "team_not_found"


async def test_get_team_deleted_returns_404(async_client, user, team, auth):
    team.deleted_at = timezone.now()
    await team.asave(update_fields=["deleted_at"])

    response = await async_client.get(url(team.id), headers=auth)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "team_not_found"


async def test_get_team_not_a_member_returns_403(async_client, auth):
    other = await sync_to_async(User.objects.create_user)(
        email="other@example.com", display_name="Other", password="correct horse battery"
    )
    other_team = await Team.objects.acreate(name="Other Team", created_by=other)
    await TeamMember.objects.acreate(team=other_team, user=other, role=TeamMember.Role.OWNER)

    response = await async_client.get(url(other_team.id), headers=auth)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_a_team_member"


async def test_get_team_requires_auth(async_client, team):
    response = await async_client.get(url(team.id))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_get_team_inactive_user(async_client, user, team, auth):
    user.is_active = False
    await user.asave(update_fields=["is_active"])

    response = await async_client.get(url(team.id), headers=auth)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "user_inactive"
