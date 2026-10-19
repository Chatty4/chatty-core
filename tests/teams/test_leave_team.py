import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from authn.services import AuthnService
from channels.models import Channel, ChannelMember
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
    return f"/api/core/v1/teams/{team_id}/leave"


async def test_leave_team_returns_204(async_client, team_with_member, member_auth):
    response = await async_client.post(url(team_with_member.id), headers=member_auth)

    assert response.status_code == 204


async def test_leave_team_returns_no_body(async_client, team_with_member, member_auth):
    response = await async_client.post(url(team_with_member.id), headers=member_auth)

    assert response.content == b""


async def test_leave_team_removes_team_membership(
    async_client, team_with_member, member, member_auth
):
    await async_client.post(url(team_with_member.id), headers=member_auth)

    still_member = await TeamMember.objects.filter(team=team_with_member, user=member).aexists()
    assert not still_member


async def test_leave_team_revokes_my_invites(async_client, team_with_member, member, member_auth):
    invite = await Invite.objects.acreate(team=team_with_member, created_by=member, code="leaver01")

    await async_client.post(url(team_with_member.id), headers=member_auth)

    await invite.arefresh_from_db()
    assert invite.revoked_at is not None


async def test_leave_team_removes_channel_memberships(
    async_client, owner, team_with_member, member, member_auth
):
    channel = await Channel.objects.acreate(
        team=team_with_member,
        name="general",
        kind=Channel.Kind.PUBLIC,
        is_default=True,
        created_by=owner,
    )
    await ChannelMember.objects.acreate(
        channel=channel,
        user=member,
        role=ChannelMember.Role.MEMBER,
        notify_level=ChannelMember.NotifyLevel.MENTIONS,
    )

    await async_client.post(url(team_with_member.id), headers=member_auth)

    still_in_channel = await ChannelMember.objects.filter(channel=channel, user=member).aexists()
    assert not still_in_channel


async def test_leave_team_last_owner_returns_409(async_client, team, owner):
    owner_tokens = await AuthnService().issue_tokens(owner)
    owner_auth = {"Authorization": f"Bearer {owner_tokens.access_token}"}

    response = await async_client.post(url(team.id), headers=owner_auth)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "last_owner"


async def test_leave_team_owner_can_leave_when_another_owner_exists(
    async_client, team, owner, member
):
    await TeamMember.objects.acreate(team=team, user=member, role=TeamMember.Role.OWNER)
    owner_tokens = await AuthnService().issue_tokens(owner)
    owner_auth = {"Authorization": f"Bearer {owner_tokens.access_token}"}

    response = await async_client.post(url(team.id), headers=owner_auth)

    assert response.status_code == 204


async def test_leave_team_non_member_returns_403(async_client, team, member):
    member_tokens = await AuthnService().issue_tokens(member)
    member_auth = {"Authorization": f"Bearer {member_tokens.access_token}"}

    response = await async_client.post(url(team.id), headers=member_auth)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_a_team_member"


async def test_leave_team_not_found(async_client, member_auth):
    response = await async_client.post(
        url("00000000-0000-0000-0000-000000000000"), headers=member_auth
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "team_not_found"


async def test_leave_team_deleted_team_returns_404(async_client, team_with_member, member_auth):
    team_with_member.deleted_at = timezone.now()
    await team_with_member.asave(update_fields=["deleted_at"])

    response = await async_client.post(url(team_with_member.id), headers=member_auth)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "team_not_found"


async def test_leave_team_requires_auth(async_client, team_with_member):
    response = await async_client.post(url(team_with_member.id))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_leave_team_inactive_user(async_client, team_with_member, member, member_auth):
    member.is_active = False
    await member.asave(update_fields=["is_active"])

    response = await async_client.post(url(team_with_member.id), headers=member_auth)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "user_inactive"
