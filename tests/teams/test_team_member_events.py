from dataclasses import asdict

import pytest

from shared.events import EventType
from shared.exceptions import AppError
from teams.models import TeamMember
from teams.schemas import TeamMemberAction, TeamMemberChanged
from teams.services import TeamService
from tests.helpers import make_user

pytestmark = pytest.mark.django_db(transaction=True)

JOINED, LEFT, REMOVED, ROLE_CHANGED = TeamMemberAction


def tmc(user, team_id, action, role):
    return (
        EventType.TEAM_MEMBER_CHANGED,
        asdict(TeamMemberChanged(user.id, team_id, action, role)),
    )


def team_events(published):
    return [e for e in published if e[0] == EventType.TEAM_MEMBER_CHANGED]


@pytest.fixture
async def world():
    """Ana owns the team, Bob is a member."""
    ana, bob = await make_user("ana@example.com"), await make_user("bob@example.com")
    team = await TeamService.create("A", ana.id)
    await TeamMember.objects.acreate(team_id=team.id, user=bob, role=TeamMember.Role.MEMBER)
    return {"ana": ana, "bob": bob, "team": team}


async def test_change_role(world, published):
    t = world["team"].id

    await TeamService.change_role(t, world["ana"].id, world["bob"].id, "admin")

    assert team_events(published) == [tmc(world["bob"], t, ROLE_CHANGED, "admin")]


async def test_refused_role_change_publishes_nothing(world, published):
    t = world["team"].id

    with pytest.raises(AppError):  # last_owner: Ana can't demote herself
        await TeamService.change_role(t, world["ana"].id, world["ana"].id, "member")

    assert published == []


async def test_remove_member(world, published):
    t = world["team"].id

    await TeamService.remove_member(t, world["ana"].id, world["bob"].id)

    assert team_events(published) == [tmc(world["bob"], t, REMOVED, None)]


async def test_leave(world, published):
    t = world["team"].id

    await TeamService.leave(t, world["bob"].id)

    assert team_events(published) == [tmc(world["bob"], t, LEFT, None)]


async def test_last_owner_leaving_publishes_nothing(world, published):
    with pytest.raises(AppError):
        await TeamService.leave(world["team"].id, world["ana"].id)

    assert published == []


async def test_owner_hand_off_after_deactivation(world, published):
    t, ana, bob = world["team"].id, world["ana"], world["bob"]
    ana.is_active = False
    await ana.asave(update_fields=["is_active"])

    await TeamService.hand_off_ownership(ana.id)

    assert team_events(published) == [tmc(bob, t, ROLE_CHANGED, "owner")]
