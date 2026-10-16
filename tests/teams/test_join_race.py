import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pytest
from asgiref.sync import sync_to_async
from django.db import connections

from channels.models import ChannelMember
from shared.exceptions import Gone
from teams.models import Invite, Team, TeamMember
from teams.services import InviteService, TeamService
from users.models import User

pytestmark = pytest.mark.django_db(transaction=True)


async def make_user(email: str) -> User:
    return await sync_to_async(User.objects.create_user)(
        email=email, display_name="Ana Pop", password="correct horse battery"
    )


async def test_parallel_joins_on_single_use_invite(monkeypatch):
    """Each join runs in its own thread and connection, like five uvicorn workers."""
    owner = await make_user("owner@example.com")
    joiners = [await make_user(f"user{i}@example.com") for i in range(5)]
    created = await TeamService.create("Backend", owner.id)
    team = await Team.objects.aget(id=created.id)
    invite = await Invite.objects.acreate(
        team=team, created_by=owner, code="race0001", max_uses=1, uses=0
    )

    original = InviteService._check_validity
    calls = []

    def slow_first_check(inv: Invite) -> tuple[bool, str | None]:
        result = original(inv)
        if not calls:  # the first join passed the check and holds the lock while the others start
            calls.append(inv.id)
            time.sleep(0.5)
        return result

    monkeypatch.setattr(InviteService, "_check_validity", staticmethod(slow_first_check))

    def join(user_id: UUID) -> str:
        try:
            InviteService._join_sync(invite.id, team, user_id)
            return "joined"
        except Gone as e:
            return e.message
        finally:
            connections.close_all()

    def run() -> list[str]:
        with ThreadPoolExecutor(len(joiners)) as pool:
            first = pool.submit(join, joiners[0].id)
            time.sleep(0.15)
            rest = [pool.submit(join, u.id) for u in joiners[1:]]
            return [first.result()] + [f.result() for f in rest]

    results = await asyncio.to_thread(run)

    assert results.count("joined") == 1
    assert results.count("used_up") == 4
    await invite.arefresh_from_db()
    assert invite.uses == 1
    assert await TeamMember.objects.filter(team=team).acount() == 2
    joined_ids = [u.id for u in joiners]
    assert (
        await ChannelMember.objects.filter(
            channel_id=created.general_channel_id, user_id__in=joined_ids
        ).acount()
        == 1
    )
