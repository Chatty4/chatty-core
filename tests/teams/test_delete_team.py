import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from authn.services import AuthnService
from teams.models import Team, TeamMember
from users.models import User

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
async def owner():
    return await sync_to_async(User.objects.create_user)(
        email="ana@example.com", display_name="Ana Pop", password="correct horse battery"
    )


@pytest.fixture
async def auth(owner):
    tokens = await AuthnService().issue_tokens(owner)
    return {"Authorization": f"Bearer {tokens.access_token}"}


@pytest.fixture
async def team(owner):
    t = await Team.objects.acreate(name="Backend", created_by=owner)
    await TeamMember.objects.acreate(team=t, user=owner, role=TeamMember.Role.OWNER)
    return t


def url(team_id):
    return f"/api/core/v1/teams/{team_id}"


async def test_delete_team_returns_204(async_client, team, auth):
    response = await async_client.delete(url(team.id), headers=auth)

    assert response.status_code == 204


async def test_delete_team_returns_no_body(async_client, team, auth):
    response = await async_client.delete(url(team.id), headers=auth)

    assert response.content == b""


async def test_delete_team_soft_deletes(async_client, team, auth):
    await async_client.delete(url(team.id), headers=auth)

    await team.arefresh_from_db()
    assert team.deleted_at is not None


async def test_delete_team_hides_from_get(async_client, team, auth):
    await async_client.delete(url(team.id), headers=auth)

    response = await async_client.get(url(team.id), headers=auth)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "team_not_found"


async def test_delete_team_admin_is_forbidden(async_client, team):
    admin = await sync_to_async(User.objects.create_user)(
        email="admin@example.com", display_name="Admin", password="correct horse battery"
    )
    await TeamMember.objects.acreate(team=team, user=admin, role=TeamMember.Role.ADMIN)
    admin_tokens = await AuthnService().issue_tokens(admin)
    admin_auth = {"Authorization": f"Bearer {admin_tokens.access_token}"}

    response = await async_client.delete(url(team.id), headers=admin_auth)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


async def test_delete_team_member_is_forbidden(async_client, team):
    member_user = await sync_to_async(User.objects.create_user)(
        email="member@example.com", display_name="Member", password="correct horse battery"
    )
    await TeamMember.objects.acreate(team=team, user=member_user, role=TeamMember.Role.MEMBER)
    member_tokens = await AuthnService().issue_tokens(member_user)
    member_auth = {"Authorization": f"Bearer {member_tokens.access_token}"}

    response = await async_client.delete(url(team.id), headers=member_auth)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


async def test_delete_team_non_member_returns_403(async_client, team):
    other = await sync_to_async(User.objects.create_user)(
        email="other@example.com", display_name="Other", password="correct horse battery"
    )
    other_tokens = await AuthnService().issue_tokens(other)
    other_auth = {"Authorization": f"Bearer {other_tokens.access_token}"}

    response = await async_client.delete(url(team.id), headers=other_auth)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_a_team_member"


async def test_delete_team_not_found(async_client, auth):
    response = await async_client.delete(url("00000000-0000-0000-0000-000000000000"), headers=auth)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "team_not_found"


async def test_delete_team_already_deleted_returns_404(async_client, team, auth):
    team.deleted_at = timezone.now()
    await team.asave(update_fields=["deleted_at"])

    response = await async_client.delete(url(team.id), headers=auth)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "team_not_found"


async def test_delete_team_requires_auth(async_client, team):
    response = await async_client.delete(url(team.id))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_delete_team_inactive_user(async_client, owner, team, auth):
    owner.is_active = False
    await owner.asave(update_fields=["is_active"])

    response = await async_client.delete(url(team.id), headers=auth)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "user_inactive"
