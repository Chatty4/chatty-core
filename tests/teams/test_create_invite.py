import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from authn.services import AuthnService
from teams.models import Invite, Team, TeamMember
from users.models import User

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
async def owner():
    return await sync_to_async(User.objects.create_user)(
        email="ana@example.com", display_name="Ana Pop", password="correct horse battery"
    )


@pytest.fixture
async def member():
    return await sync_to_async(User.objects.create_user)(
        email="bob@example.com", display_name="Bob Pop", password="correct horse battery"
    )


@pytest.fixture
async def owner_auth(owner):
    tokens = await AuthnService().issue_tokens(owner)
    return {"Authorization": f"Bearer {tokens.access_token}"}


@pytest.fixture
async def member_auth(member):
    tokens = await AuthnService().issue_tokens(member)
    return {"Authorization": f"Bearer {tokens.access_token}"}


@pytest.fixture
async def team(owner):
    t = await Team.objects.acreate(name="Backend", created_by=owner)
    await TeamMember.objects.acreate(team=t, user=owner, role=TeamMember.Role.OWNER)
    return t


@pytest.fixture
async def team_with_member(team, member):
    await TeamMember.objects.acreate(team=team, user=member, role=TeamMember.Role.MEMBER)
    return team


def url(team_id):
    return f"/api/core/v1/teams/{team_id}/invites"


# --- status and shape ---


async def test_create_invite_returns_201(async_client, team, owner_auth):
    response = await async_client.post(url(team.id), headers=owner_auth)

    assert response.status_code == 201


async def test_create_invite_response_shape(async_client, team, owner_auth):
    response = await async_client.post(url(team.id), headers=owner_auth)

    body = response.json()
    assert "id" in body
    assert "code" in body
    assert "url" in body
    assert "team_id" in body
    assert "created_by" in body
    assert "max_uses" in body
    assert "uses" in body
    assert "expires_at" in body
    assert "created_at" in body


async def test_create_invite_uses_is_zero(async_client, team, owner_auth):
    response = await async_client.post(url(team.id), headers=owner_auth)

    assert response.json()["uses"] == 0


async def test_create_invite_url_contains_code(async_client, team, owner_auth):
    response = await async_client.post(url(team.id), headers=owner_auth)

    body = response.json()
    assert body["code"] in body["url"]


async def test_create_invite_team_id_matches(async_client, team, owner_auth):
    response = await async_client.post(url(team.id), headers=owner_auth)

    assert response.json()["team_id"] == str(team.id)


async def test_create_invite_created_by_matches_owner(async_client, team, owner, owner_auth):
    response = await async_client.post(url(team.id), headers=owner_auth)

    assert response.json()["created_by"] == str(owner.id)


# --- defaults ---


async def test_create_invite_default_max_uses_is_zero(async_client, team, owner_auth):
    response = await async_client.post(url(team.id), headers=owner_auth)

    assert response.json()["max_uses"] == 0


async def test_create_invite_default_expires_at_is_set(async_client, team, owner_auth):
    response = await async_client.post(url(team.id), headers=owner_auth)

    # default max_age = 604800 (7 days), so expires_at must not be null
    assert response.json()["expires_at"] is not None


async def test_create_invite_max_age_zero_gives_null_expires_at(async_client, team, owner_auth):
    response = await async_client.post(
        url(team.id),
        data={"max_age": 0, "max_uses": 0},
        content_type="application/json",
        headers=owner_auth,
    )

    assert response.json()["expires_at"] is None


async def test_create_invite_max_uses_set(async_client, team, owner_auth):
    response = await async_client.post(
        url(team.id),
        data={"max_age": 0, "max_uses": 10},
        content_type="application/json",
        headers=owner_auth,
    )

    assert response.json()["max_uses"] == 10


# --- persisted in DB ---


async def test_create_invite_row_created_in_db(async_client, team, owner_auth):
    await async_client.post(url(team.id), headers=owner_auth)

    assert await Invite.objects.filter(team=team).acount() == 1


# --- any member can create ---


async def test_create_invite_member_can_create(async_client, team_with_member, member_auth):
    response = await async_client.post(url(team_with_member.id), headers=member_auth)

    assert response.status_code == 201


# --- validation ---


async def test_create_invite_invalid_max_age_returns_400(async_client, team, owner_auth):
    response = await async_client.post(
        url(team.id),
        data={"max_age": 9999, "max_uses": 0},
        content_type="application/json",
        headers=owner_auth,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


async def test_create_invite_invalid_max_uses_returns_400(async_client, team, owner_auth):
    response = await async_client.post(
        url(team.id),
        data={"max_age": 0, "max_uses": 99},
        content_type="application/json",
        headers=owner_auth,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


# --- invite cap ---


async def test_create_invite_limit_reached_returns_409(async_client, team, owner, owner_auth):
    await sync_to_async(
        lambda: Invite.objects.bulk_create(
            [
                Invite(
                    team=team,
                    created_by=owner,
                    code=f"code{i:04d}",
                    max_uses=0,
                    uses=0,
                )
                for i in range(100)
            ]
        )
    )()

    response = await async_client.post(url(team.id), headers=owner_auth)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invite_limit_reached"


# --- auth / membership ---


async def test_create_invite_non_member_returns_403(async_client, team, member_auth):
    response = await async_client.post(url(team.id), headers=member_auth)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_a_team_member"


async def test_create_invite_team_not_found_returns_404(async_client, owner_auth):
    response = await async_client.post(
        url("00000000-0000-0000-0000-000000000000"), headers=owner_auth
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "team_not_found"


async def test_create_invite_deleted_team_returns_404(async_client, team, owner_auth):
    team.deleted_at = timezone.now()
    await team.asave(update_fields=["deleted_at"])

    response = await async_client.post(url(team.id), headers=owner_auth)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "team_not_found"


async def test_create_invite_requires_auth(async_client, team):
    response = await async_client.post(url(team.id))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_create_invite_inactive_user(async_client, team, owner, owner_auth):
    owner.is_active = False
    await owner.asave(update_fields=["is_active"])

    response = await async_client.post(url(team.id), headers=owner_auth)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "user_inactive"
