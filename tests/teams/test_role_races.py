import asyncio
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pytest
from asgiref.sync import sync_to_async
from django.db import connections

from shared.exceptions import AppError
from teams.models import Team, TeamMember
from teams.repositories import TeamMemberRepository
from teams.services import TeamService
from users.models import User

pytestmark = pytest.mark.django_db(transaction=True)

OWNER, ADMIN, MEMBER = TeamMember.Role.OWNER, TeamMember.Role.ADMIN, TeamMember.Role.MEMBER


async def make_user(email: str) -> User:
    return await sync_to_async(User.objects.create_user)(
        email=email, display_name="Ana Pop", password="correct horse battery"
    )


@pytest.fixture(autouse=True)
def slow_first_lock(monkeypatch):
    """The first request holds the team lock for 0.5 s while the second one starts."""
    original = TeamMemberRepository.lock_owner_ids_sync
    calls = []

    def slow(team_id: UUID) -> list[UUID]:
        ids = original(team_id)
        if not calls:
            calls.append(team_id)
            time.sleep(0.5)
        return ids

    monkeypatch.setattr(TeamMemberRepository, "lock_owner_ids_sync", staticmethod(slow))


def overlapping(first: Callable[[], object], second: Callable[[], object]) -> tuple[str, str]:
    """Run two requests like two uvicorn workers. Returns "ok" or the error code of each."""

    def call(fn: Callable[[], object]) -> str:
        try:
            fn()
            return "ok"
        except AppError as e:
            return str(e.code)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(2) as pool:
        a = pool.submit(call, first)
        time.sleep(0.15)
        b = pool.submit(call, second)
        return a.result(), b.result()


async def setup_team(**roles: str) -> tuple[Team, dict[str, User]]:
    users = {name: await make_user(f"{name}@example.com") for name in ["ana", *roles]}
    created = await TeamService.create("Backend", users["ana"].id)
    for name, role in roles.items():
        await TeamMember.objects.acreate(team_id=created.id, user=users[name], role=role)
    return await Team.objects.aget(id=created.id), users


async def role_of(team: Team, user: User) -> str | None:
    member = await TeamMember.objects.filter(team=team, user=user).afirst()
    return member.role if member else None


async def test_owners_removing_each_other_keeps_one_owner():
    team, u = await setup_team(bob=OWNER)

    results = await asyncio.to_thread(
        overlapping,
        lambda: TeamService._remove_sync(team.id, u["ana"].id, u["bob"].id),
        lambda: TeamService._remove_sync(team.id, u["bob"].id, u["ana"].id),
    )

    assert results == ("ok", "not_a_team_member")
    assert await role_of(team, u["ana"]) == OWNER
    assert await role_of(team, u["bob"]) is None


async def test_demoted_owner_cannot_promote_to_owner():
    team, u = await setup_team(bob=OWNER, carl=MEMBER)

    results = await asyncio.to_thread(
        overlapping,
        lambda: TeamService._change_role_sync(team.id, u["ana"].id, u["bob"].id, ADMIN),
        lambda: TeamService._change_role_sync(team.id, u["bob"].id, u["carl"].id, OWNER),
    )

    assert results == ("ok", "forbidden")
    assert await role_of(team, u["carl"]) == MEMBER


async def test_admin_cannot_remove_member_just_promoted_to_owner():
    team, u = await setup_team(dan=ADMIN, carl=MEMBER)

    results = await asyncio.to_thread(
        overlapping,
        lambda: TeamService._change_role_sync(team.id, u["ana"].id, u["carl"].id, OWNER),
        lambda: TeamService._remove_sync(team.id, u["dan"].id, u["carl"].id),
    )

    assert results == ("ok", "forbidden")
    assert await role_of(team, u["carl"]) == OWNER


async def test_last_owner_can_leave_once_promotion_commits():
    team, u = await setup_team(bob=MEMBER)

    results = await asyncio.to_thread(
        overlapping,
        lambda: TeamService._change_role_sync(team.id, u["ana"].id, u["bob"].id, OWNER),
        lambda: TeamService._leave_sync(team.id, u["ana"].id),
    )

    assert results == ("ok", "ok")
    assert await role_of(team, u["bob"]) == OWNER
    assert await role_of(team, u["ana"]) is None
