import pytest

from channels.models import Channel
from channels.services import ChannelService
from shared.codes import ErrorCode
from shared.exceptions import PermissionDenied
from teams.models import Team, TeamMember
from teams.repositories import TeamRepository
from teams.services import TeamService
from tests.helpers import hold_first_lock, make_user, run_overlapping

pytestmark = pytest.mark.django_db(transaction=True)


async def test_create_waits_for_a_team_removal_and_is_refused(monkeypatch):
    owner = await make_user("owner@example.com")
    member = await make_user("member@example.com")
    created = await TeamService.create("Backend", owner.id)
    team = await Team.objects.aget(id=created.id)
    await TeamMember.objects.acreate(team=team, user=member, role=TeamMember.Role.MEMBER)
    hold_first_lock(monkeypatch, TeamRepository, "lock_sync")

    removal, create = await run_overlapping(
        lambda: TeamService._remove_sync(team.id, owner.id, member.id),
        lambda: ChannelService._create_sync(team, member.id, "random", Channel.Kind.PUBLIC, ""),
    )

    removal.result()
    with pytest.raises(PermissionDenied) as error:
        create.result()
    assert error.value.code == ErrorCode.NOT_A_TEAM_MEMBER
    assert not await Channel.objects.filter(team=team, name="random").aexists()
