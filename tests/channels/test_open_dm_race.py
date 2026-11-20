import time

import pytest

from channels.models import Channel, ChannelMember
from channels.repositories.channels import ChannelRepository
from channels.services import ChannelService
from shared.codes import ErrorCode
from shared.exceptions import BadRequest
from teams.models import Team, TeamMember
from teams.repositories import TeamRepository
from teams.services import TeamService
from tests.helpers import hold_first_lock, make_user, run_overlapping

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
async def setup():
    ana = await make_user("ana@example.com")
    bob = await make_user("bob@example.com")
    created = await TeamService.create("Backend", ana.id)
    team = await Team.objects.aget(id=created.id)
    await TeamMember.objects.acreate(team=team, user=bob, role=TeamMember.Role.MEMBER)
    return team, ana, bob


async def _removal_races_open(monkeypatch, team, ana, bob):
    """Ana removes Bob while she opens a DM with him; the removal takes the lock first."""
    hold_first_lock(monkeypatch, TeamRepository, "lock_sync")
    return await run_overlapping(
        lambda: TeamService._remove_sync(team.id, ana.id, bob.id),
        lambda: ChannelService._open_dm_sync(team, ana.id, [bob.id]),
    )


async def test_new_dm_waits_for_a_team_removal_and_is_refused(monkeypatch, setup):
    team, ana, bob = setup

    removal, opened = await _removal_races_open(monkeypatch, team, ana, bob)

    removal.result()
    with pytest.raises(BadRequest) as error:
        opened.result()
    assert error.value.code == ErrorCode.USER_NOT_IN_TEAM
    assert not await Channel.objects.filter(team=team, kind=Channel.Kind.DM).aexists()


async def test_existing_dm_waits_for_a_team_removal_and_is_refused(monkeypatch, setup):
    team, ana, bob = setup
    await ChannelService.open_dm(team.id, ana.id, [bob.id])

    removal, opened = await _removal_races_open(monkeypatch, team, ana, bob)

    removal.result()
    with pytest.raises(BadRequest):
        opened.result()
    assert not await ChannelMember.objects.filter(
        channel__team=team, channel__kind=Channel.Kind.DM, user=bob
    ).aexists()


async def test_same_new_dm_opened_twice_at_once_creates_it_once(monkeypatch, setup):
    team, ana, bob = setup
    original = ChannelRepository.find_dm_sync
    calls = []

    def slow_find(team_id, dm_key):  # the first open waits here, after finding no DM
        found = original(team_id, dm_key)
        if not calls:
            calls.append(dm_key)
            time.sleep(0.5)
        return found

    monkeypatch.setattr(ChannelRepository, "find_dm_sync", staticmethod(slow_find))

    first, second = await run_overlapping(
        lambda: ChannelService._open_dm_sync(team, ana.id, [bob.id]),
        lambda: ChannelService._open_dm_sync(team, bob.id, [ana.id]),
    )

    first_channel, _, first_created = first.result()
    second_channel, second_added, second_created = second.result()
    assert (first_created, second_created) == (True, False)
    assert second_channel.id == first_channel.id
    assert second_added == []
