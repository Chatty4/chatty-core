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


@pytest.fixture
async def invite(team, owner):
    return await Invite.objects.acreate(
        team=team, created_by=owner, code="owninv01", max_uses=0, uses=0
    )


@pytest.fixture
async def member_invite(team_with_member, member):
    return await Invite.objects.acreate(
        team=team_with_member, created_by=member, code="mbrinv01", max_uses=0, uses=0
    )


def url(invite_id):
    return f"/api/core/v1/invites/{invite_id}"


# --- status and shape ---


async def test_revoke_invite_returns_204(async_client, invite, owner_auth):
    response = await async_client.delete(url(invite.id), headers=owner_auth)

    assert response.status_code == 204


async def test_revoke_invite_returns_no_body(async_client, invite, owner_auth):
    response = await async_client.delete(url(invite.id), headers=owner_auth)

    assert response.content == b""


# --- DB state ---


async def test_revoke_invite_sets_revoked_at(async_client, invite, owner_auth):
    await async_client.delete(url(invite.id), headers=owner_auth)

    await invite.arefresh_from_db()
    assert invite.revoked_at is not None


# --- idempotency ---


async def test_revoke_invite_already_revoked_returns_204(async_client, invite, owner_auth):
    invite.revoked_at = timezone.now()
    await invite.asave(update_fields=["revoked_at"])

    response = await async_client.delete(url(invite.id), headers=owner_auth)

    assert response.status_code == 204


# --- who can revoke ---


async def test_revoke_invite_creator_member_can_revoke_own(
    async_client, member_invite, member_auth
):
    response = await async_client.delete(url(member_invite.id), headers=member_auth)

    assert response.status_code == 204


async def test_revoke_invite_admin_can_revoke_others(
    async_client, member_invite, member, member_auth
):
    await TeamMember.objects.filter(team=member_invite.team, user=member).aupdate(
        role=TeamMember.Role.ADMIN
    )

    response = await async_client.delete(url(member_invite.id), headers=member_auth)

    assert response.status_code == 204


async def test_revoke_invite_plain_member_cannot_revoke_others(
    async_client, invite, member_auth, team_with_member
):
    response = await async_client.delete(url(invite.id), headers=member_auth)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


# --- not found ---


async def test_revoke_invite_not_found_returns_404(async_client, owner_auth):
    response = await async_client.delete(
        url("00000000-0000-0000-0000-000000000000"), headers=owner_auth
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "invite_not_found"


async def test_revoke_invite_deleted_team_returns_404(async_client, invite, team, owner_auth):
    team.deleted_at = timezone.now()
    await team.asave(update_fields=["deleted_at"])

    response = await async_client.delete(url(invite.id), headers=owner_auth)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "invite_not_found"


# --- auth / membership ---


async def test_revoke_invite_non_member_returns_403(async_client, invite, member_auth):
    response = await async_client.delete(url(invite.id), headers=member_auth)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_a_team_member"


async def test_revoke_invite_requires_auth(async_client, invite):
    response = await async_client.delete(url(invite.id))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_revoke_invite_inactive_user(async_client, invite, owner, owner_auth):
    owner.is_active = False
    await owner.asave(update_fields=["is_active"])

    response = await async_client.delete(url(invite.id), headers=owner_auth)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "user_inactive"
