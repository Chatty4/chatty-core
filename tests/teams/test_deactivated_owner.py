import uuid

import pytest

from shared.codes import ErrorCode
from shared.exceptions import Conflict
from teams.models import TeamMember
from teams.services import TeamService
from tests.helpers import make_user
from users.models import User
from users.services import UserService

pytestmark = pytest.mark.django_db(transaction=True)

OWNER, ADMIN, MEMBER = TeamMember.Role.OWNER, TeamMember.Role.ADMIN, TeamMember.Role.MEMBER


async def join(team, role: str, is_active: bool = True) -> User:
    user = await make_user(f"{uuid.uuid4().hex}@example.com")
    if not is_active:
        await User.objects.filter(id=user.id).aupdate(is_active=False)
    await TeamMember.objects.acreate(team_id=team.id, user=user, role=role)
    return user


async def role_of(team, user) -> str:
    return (await TeamMember.objects.aget(team_id=team.id, user=user)).role


@pytest.fixture
async def owner():
    return await make_user("owner@example.com")


@pytest.fixture
async def team(owner):
    return await TeamService.create("Backend", owner.id)


async def test_first_active_admin_becomes_owner(owner, team):
    member = await join(team, MEMBER)  # joined first, but admins come before members
    await join(team, ADMIN, is_active=False)  # inactive people are skipped
    admin = await join(team, ADMIN)
    later_admin = await join(team, ADMIN)

    await UserService.deactivate([owner.id])

    assert await role_of(team, admin) == OWNER
    assert await role_of(team, later_admin) == ADMIN
    assert await role_of(team, member) == MEMBER
    assert await role_of(team, owner) == OWNER  # the deactivated owner keeps their role


async def test_first_member_becomes_owner_without_admins(owner, team):
    first = await join(team, MEMBER)
    second = await join(team, MEMBER)

    await UserService.deactivate([owner.id])

    assert await role_of(team, first) == OWNER
    assert await role_of(team, second) == MEMBER


async def test_nothing_changes_with_another_active_owner(owner, team):
    other_owner = await join(team, OWNER)
    admin = await join(team, ADMIN)

    await UserService.deactivate([owner.id])

    assert await role_of(team, other_owner) == OWNER
    assert await role_of(team, admin) == ADMIN


async def test_new_owner_cannot_leave_as_last_active_owner(owner, team):
    admin = await join(team, ADMIN)
    await UserService.deactivate([owner.id])

    with pytest.raises(Conflict) as caught:
        await TeamService.leave(team.id, admin.id)

    assert caught.value.code == ErrorCode.LAST_OWNER
