import uuid

import pytest

from channels.models import ChannelMember
from teams.models import TeamMember
from teams.services import TeamService
from tests.helpers import headers_for, make_user
from users.models import User

pytestmark = pytest.mark.django_db(transaction=True)

OWNER, ADMIN, MEMBER = TeamMember.Role.OWNER, TeamMember.Role.ADMIN, TeamMember.Role.MEMBER


async def join(team, role: str, user: User | None = None) -> User:
    """Add a user to the team and its general channel."""
    user = user or await make_user(f"{uuid.uuid4().hex}@example.com")
    await TeamMember.objects.acreate(team_id=team.id, user=user, role=role)
    await ChannelMember.objects.acreate(
        channel_id=team.general_channel_id,
        user=user,
        role=ChannelMember.Role.MEMBER,
        notify_level=ChannelMember.NotifyLevel.MENTIONS,
    )
    return user


@pytest.fixture
async def owner():
    return await make_user("owner@example.com")


@pytest.fixture
async def team(owner):
    return await TeamService.create("Backend", owner.id)


async def remove(client, team, target, as_user):
    return await client.delete(
        f"/api/core/v1/teams/{team.id}/members/{target.id}", headers=await headers_for(as_user)
    )


async def in_team(team, user) -> bool:
    return await TeamMember.objects.filter(team_id=team.id, user=user).aexists()


async def in_channels(team, user) -> bool:
    return await ChannelMember.objects.filter(channel__team_id=team.id, user=user).aexists()


async def test_owner_removes_member_from_team_and_channels(async_client, owner, team):
    member = await join(team, MEMBER)

    response = await remove(async_client, team, member, owner)

    assert response.status_code == 204
    assert not await in_team(team, member)
    assert not await in_channels(team, member)


async def test_other_teams_are_untouched(async_client, owner, team):
    member = await join(team, MEMBER)
    other_team = await TeamService.create("Frontend", owner.id)
    await join(other_team, MEMBER, user=member)

    await remove(async_client, team, member, owner)

    assert await in_team(other_team, member)
    assert await in_channels(other_team, member)


async def test_admin_removes_member(async_client, team):
    admin = await join(team, ADMIN)
    member = await join(team, MEMBER)

    response = await remove(async_client, team, member, admin)

    assert response.status_code == 204


async def test_owner_removes_another_owner(async_client, owner, team):
    other_owner = await join(team, OWNER)

    response = await remove(async_client, team, other_owner, owner)

    assert response.status_code == 204


@pytest.mark.parametrize(
    ("caller_role", "target_role"),
    [
        (MEMBER, MEMBER),  # members can't remove anyone
        (ADMIN, OWNER),  # admins can't remove owners
    ],
)
async def test_forbidden_removals(async_client, team, caller_role, target_role):
    caller = await join(team, caller_role)
    target = await join(team, target_role)

    response = await remove(async_client, team, target, caller)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
    assert await in_team(team, target)


async def test_removing_yourself_says_use_leave(async_client, owner, team):
    response = await remove(async_client, team, owner, owner)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "use_leave"
    assert await in_team(team, owner)


async def test_target_outside_the_team_is_not_found(async_client, owner, team):
    outsider = await make_user("out@example.com")

    response = await remove(async_client, team, outsider, owner)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "member_not_found"
