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


async def test_update_team_returns_200(async_client, team, auth):
    response = await async_client.put(
        url(team.id),
        data={"name": "Backend Team", "icon_file_id": None},
        content_type="application/json",
        headers=auth,
    )

    assert response.status_code == 200


async def test_update_team_returns_correct_fields(async_client, owner, team, auth):
    response = await async_client.put(
        url(team.id),
        data={"name": "Backend Team", "icon_file_id": None},
        content_type="application/json",
        headers=auth,
    )

    body = response.json()
    assert body["id"] == str(team.id)
    assert body["name"] == "Backend Team"
    assert body["icon_file_id"] is None
    assert body["my_role"] == "owner"
    assert body["member_count"] == 1
    assert body["created_by"] == str(owner.id)
    assert body["created_at"]


async def test_update_team_persists_name(async_client, team, auth):
    await async_client.put(
        url(team.id),
        data={"name": "New Name", "icon_file_id": None},
        content_type="application/json",
        headers=auth,
    )

    await team.arefresh_from_db()
    assert team.name == "New Name"


async def test_update_team_admin_can_update(async_client, team):
    admin = await sync_to_async(User.objects.create_user)(
        email="admin@example.com", display_name="Admin", password="correct horse battery"
    )
    await TeamMember.objects.acreate(team=team, user=admin, role=TeamMember.Role.ADMIN)
    admin_tokens = await AuthnService().issue_tokens(admin)
    admin_auth = {"Authorization": f"Bearer {admin_tokens.access_token}"}

    response = await async_client.put(
        url(team.id),
        data={"name": "Updated", "icon_file_id": None},
        content_type="application/json",
        headers=admin_auth,
    )

    assert response.status_code == 200


async def test_update_team_member_is_forbidden(async_client, team):
    member_user = await sync_to_async(User.objects.create_user)(
        email="member@example.com", display_name="Member", password="correct horse battery"
    )
    await TeamMember.objects.acreate(team=team, user=member_user, role=TeamMember.Role.MEMBER)
    member_tokens = await AuthnService().issue_tokens(member_user)
    member_auth = {"Authorization": f"Bearer {member_tokens.access_token}"}

    response = await async_client.put(
        url(team.id),
        data={"name": "Updated", "icon_file_id": None},
        content_type="application/json",
        headers=member_auth,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


async def test_update_team_non_member_returns_403(async_client, team):
    other = await sync_to_async(User.objects.create_user)(
        email="other@example.com", display_name="Other", password="correct horse battery"
    )
    other_tokens = await AuthnService().issue_tokens(other)
    other_auth = {"Authorization": f"Bearer {other_tokens.access_token}"}

    response = await async_client.put(
        url(team.id),
        data={"name": "Updated", "icon_file_id": None},
        content_type="application/json",
        headers=other_auth,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_a_team_member"


async def test_update_team_not_found(async_client, auth):
    response = await async_client.put(
        url("00000000-0000-0000-0000-000000000000"),
        data={"name": "Updated", "icon_file_id": None},
        content_type="application/json",
        headers=auth,
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "team_not_found"


async def test_update_team_deleted_returns_404(async_client, team, auth):
    team.deleted_at = timezone.now()
    await team.asave(update_fields=["deleted_at"])

    response = await async_client.put(
        url(team.id),
        data={"name": "Updated", "icon_file_id": None},
        content_type="application/json",
        headers=auth,
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "team_not_found"


async def test_update_team_empty_name_returns_400(async_client, team, auth):
    response = await async_client.put(
        url(team.id),
        data={"name": "", "icon_file_id": None},
        content_type="application/json",
        headers=auth,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


async def test_update_team_name_too_long_returns_400(async_client, team, auth):
    response = await async_client.put(
        url(team.id),
        data={"name": "a" * 81, "icon_file_id": None},
        content_type="application/json",
        headers=auth,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


async def test_update_team_requires_auth(async_client, team):
    response = await async_client.put(
        url(team.id),
        data={"name": "Updated", "icon_file_id": None},
        content_type="application/json",
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_update_team_inactive_user(async_client, owner, team, auth):
    owner.is_active = False
    await owner.asave(update_fields=["is_active"])

    response = await async_client.put(
        url(team.id),
        data={"name": "Updated", "icon_file_id": None},
        content_type="application/json",
        headers=auth,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "user_inactive"
