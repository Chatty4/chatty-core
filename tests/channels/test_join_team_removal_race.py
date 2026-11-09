import asyncio
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import connections

from channels.models import Channel, ChannelMember
from channels.repositories import ChannelMemberRepository
from channels.services import ChannelService
from shared.exceptions import PermissionDenied
from teams.models import Team, TeamMember
from teams.services import TeamService
from tests.helpers import make_user

pytestmark = pytest.mark.django_db(transaction=True)


async def test_join_waits_for_a_team_removal_and_is_refused(monkeypatch):
    """The removal and the join run in their own threads and connections, like two workers."""
    owner = await make_user("owner@example.com")
    member = await make_user("member@example.com")
    created = await TeamService.create("Backend", owner.id)
    team = await Team.objects.aget(id=created.id)
    await TeamMember.objects.acreate(team=team, user=member, role=TeamMember.Role.MEMBER)
    channel = await ChannelService.create(team.id, owner.id, "random", Channel.Kind.PUBLIC, "")

    original = ChannelMemberRepository.delete_in_team_sync

    def slow_delete(team_id, user_id):  # the removal holds the team lock while the join starts
        original(team_id, user_id)
        time.sleep(0.5)

    monkeypatch.setattr(ChannelMemberRepository, "delete_in_team_sync", staticmethod(slow_delete))

    def remove() -> str:
        try:
            TeamService._remove_sync(team.id, owner.id, member.id)
            return "removed"
        finally:
            connections.close_all()

    def join() -> str:
        try:
            ChannelService._join_sync(team.id, channel.id, member.id)
            return "joined"
        except PermissionDenied:
            return "refused"
        finally:
            connections.close_all()

    def run() -> list[str]:
        with ThreadPoolExecutor(2) as pool:
            first = pool.submit(remove)
            time.sleep(0.15)
            second = pool.submit(join)
            return [first.result(), second.result()]

    assert await asyncio.to_thread(run) == ["removed", "refused"]
    assert not await ChannelMember.objects.filter(channel=channel, user=member).aexists()
