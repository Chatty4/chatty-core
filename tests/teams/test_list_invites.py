import secrets
from datetime import timedelta

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
async def other():
    return await sync_to_async(User.objects.create_user)(
        email="carol@example.com", display_name="Carol Pop", password="correct horse battery"
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


async def make_invite(team, created_by, **kwargs):
    return await Invite.objects.acreate(
        team=team,
        created_by=created_by,
        code=kwargs.pop("code", secrets.token_urlsafe(6)),
        max_uses=kwargs.pop("max_uses", 0),
        uses=kwargs.pop("uses", 0),
        **kwargs,
    )


# --- status and shape ---


async def test_list_invites_returns_200(async_client, team, owner_auth):
    response = await async_client.get(url(team.id), headers=owner_auth)

    assert response.status_code == 200


async def test_list_invites_returns_invites_key(async_client, team, owner_auth):
    response = await async_client.get(url(team.id), headers=owner_auth)

    assert "invites" in response.json()


async def test_list_invites_empty_when_no_invites(async_client, team, owner_auth):
    response = await async_client.get(url(team.id), headers=owner_auth)

    assert response.json()["invites"] == []


async def test_list_invites_item_shape(async_client, team, owner, owner_auth):
    await make_invite(team, owner, code="abcd1234")

    response = await async_client.get(url(team.id), headers=owner_auth)
    item = response.json()["invites"][0]

    assert "id" in item
    assert "code" in item
    assert "url" in item
    assert "created_by" in item
    assert "max_uses" in item
    assert "uses" in item
    assert "expires_at" in item
    assert "created_at" in item
    assert "team_id" not in item  # team_id is not in the list response


# --- visibility ---


async def test_list_invites_owner_sees_all(
    async_client, team_with_member, owner, member, owner_auth
):
    await make_invite(team_with_member, owner, code="owninv01")
    await make_invite(team_with_member, member, code="mbrinv01")

    response = await async_client.get(url(team_with_member.id), headers=owner_auth)

    assert len(response.json()["invites"]) == 2


async def test_list_invites_member_sees_only_own(
    async_client, team_with_member, owner, member, member_auth
):
    await make_invite(team_with_member, owner, code="owninv01")
    await make_invite(team_with_member, member, code="mbrinv01")

    response = await async_client.get(url(team_with_member.id), headers=member_auth)

    invites = response.json()["invites"]
    assert len(invites) == 1
    assert invites[0]["created_by"] == str(member.id)


async def test_list_invites_admin_sees_all(
    async_client, team_with_member, owner, member, member_auth
):
    await TeamMember.objects.filter(team=team_with_member, user=member).aupdate(
        role=TeamMember.Role.ADMIN
    )
    await make_invite(team_with_member, owner, code="owninv01")
    await make_invite(team_with_member, member, code="mbrinv01")

    response = await async_client.get(url(team_with_member.id), headers=member_auth)

    assert len(response.json()["invites"]) == 2


# --- active filter ---


async def test_list_invites_excludes_revoked(async_client, team, owner, owner_auth):
    await make_invite(team, owner, code="active01", revoked_at=None)
    await make_invite(team, owner, code="revoked1", revoked_at=timezone.now())

    response = await async_client.get(url(team.id), headers=owner_auth)

    assert len(response.json()["invites"]) == 1


async def test_list_invites_excludes_expired(async_client, team, owner, owner_auth):
    await make_invite(team, owner, code="active01", expires_at=None)
    await make_invite(
        team, owner, code="expired1", expires_at=timezone.now() - timedelta(seconds=1)
    )

    response = await async_client.get(url(team.id), headers=owner_auth)

    assert len(response.json()["invites"]) == 1


async def test_list_invites_excludes_used_up(async_client, team, owner, owner_auth):
    await make_invite(team, owner, code="active01", max_uses=0, uses=0)
    await make_invite(team, owner, code="usedup1", max_uses=5, uses=5)

    response = await async_client.get(url(team.id), headers=owner_auth)

    assert len(response.json()["invites"]) == 1


async def test_list_invites_includes_not_yet_expired(async_client, team, owner, owner_auth):
    await make_invite(team, owner, code="future01", expires_at=timezone.now() + timedelta(hours=1))

    response = await async_client.get(url(team.id), headers=owner_auth)

    assert len(response.json()["invites"]) == 1


# --- auth / membership ---


async def test_list_invites_non_member_returns_403(async_client, team, member_auth):
    response = await async_client.get(url(team.id), headers=member_auth)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_a_team_member"


async def test_list_invites_team_not_found_returns_404(async_client, owner_auth):
    response = await async_client.get(
        url("00000000-0000-0000-0000-000000000000"), headers=owner_auth
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "team_not_found"


async def test_list_invites_deleted_team_returns_404(async_client, team, owner_auth):
    team.deleted_at = timezone.now()
    await team.asave(update_fields=["deleted_at"])

    response = await async_client.get(url(team.id), headers=owner_auth)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "team_not_found"


async def test_list_invites_requires_auth(async_client, team):
    response = await async_client.get(url(team.id))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_list_invites_inactive_user(async_client, team, owner, owner_auth):
    owner.is_active = False
    await owner.asave(update_fields=["is_active"])

    response = await async_client.get(url(team.id), headers=owner_auth)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "user_inactive"
