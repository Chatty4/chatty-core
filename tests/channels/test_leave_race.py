import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import UUID

import pytest
from asgiref.sync import sync_to_async
from django.db import connections
from django.utils import timezone

from channels.models import Channel, ChannelMember
from channels.repositories import ChannelMemberRepository
from channels.services import ChannelService
from teams.models import TeamMember
from teams.services import TeamService
from users.models import User

pytestmark = pytest.mark.django_db(transaction=True)


async def make_user(email: str) -> User:
    return await sync_to_async(User.objects.create_user)(
        email=email, display_name="Ana Pop", password="correct horse battery"
    )


async def test_last_owner_and_first_joined_leave_at_once(monkeypatch):
    """Each leave runs in its own thread and connection, like two uvicorn workers."""
    owner, ana, bob, cara = [await make_user(f"{n}@example.com") for n in ("o", "a", "b", "c")]
    team = await TeamService.create("Backend", owner.id)
    secret = await Channel.objects.acreate(
        team_id=team.id, name="secret", kind=Channel.Kind.PRIVATE
    )
    for hours, (user, role) in enumerate(
        [
            (ana, ChannelMember.Role.OWNER),
            (bob, ChannelMember.Role.MEMBER),
            (cara, ChannelMember.Role.MEMBER),
        ]
    ):
        await TeamMember.objects.acreate(team_id=team.id, user=user, role=TeamMember.Role.MEMBER)
        member = await ChannelMember.objects.acreate(
            channel=secret, user=user, role=role, notify_level=ChannelMember.NotifyLevel.ALL
        )
        await ChannelMember.objects.filter(pk=member.pk).aupdate(
            joined_at=timezone.now() + timedelta(hours=hours)
        )

    original = ChannelMemberRepository.lock_owner_ids_sync
    calls = []

    def slow_first_call(channel_id: UUID) -> list[UUID]:
        ids = original(channel_id)
        if not calls:  # ana's leave holds the lock while bob's leave starts
            calls.append(channel_id)
            time.sleep(0.5)
        return ids

    monkeypatch.setattr(
        ChannelMemberRepository, "lock_owner_ids_sync", staticmethod(slow_first_call)
    )

    def leave(user_id: UUID) -> None:
        try:
            ChannelService._leave_sync(secret, user_id)
        finally:
            connections.close_all()

    def run() -> None:
        with ThreadPoolExecutor(2) as pool:
            first = pool.submit(leave, ana.id)
            time.sleep(0.15)
            second = pool.submit(leave, bob.id)
            first.result()
            second.result()

    await asyncio.to_thread(run)

    owners = [m.user_id async for m in ChannelMember.objects.filter(channel=secret, role="owner")]  # type: ignore
    assert owners == [cara.id]
