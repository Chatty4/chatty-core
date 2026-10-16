import pytest

from shared.codes import ErrorCode
from shared.exceptions import PermissionDenied
from teams.models import TeamMember
from teams.services import TeamService
from tests.helpers import make_user

pytestmark = pytest.mark.django_db(transaction=True)

ADMINS = {TeamMember.Role.OWNER, TeamMember.Role.ADMIN}


async def test_role_outside_roles_is_forbidden():
    owner = await make_user("ana@example.com")
    member = await make_user("bob@example.com")
    team = await TeamService.create("Backend", owner.id)
    await TeamMember.objects.acreate(team_id=team.id, user=member, role=TeamMember.Role.MEMBER)

    with pytest.raises(PermissionDenied) as caught:
        await TeamService.require_member(team.id, member.id, roles=ADMINS)

    assert caught.value.code == ErrorCode.FORBIDDEN


async def test_role_inside_roles_passes():
    owner = await make_user("ana@example.com")
    team = await TeamService.create("Backend", owner.id)

    _team, member = await TeamService.require_member(team.id, owner.id, roles=ADMINS)

    assert member.role == TeamMember.Role.OWNER
