import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pytest
from asgiref.sync import sync_to_async
from django.db import connections

from shared.exceptions import AppError
from teams.models import Team
from teams.repositories import TeamRepository
from teams.services import TeamService
from users.models import User

pytestmark = pytest.mark.django_db(transaction=True)


def create(user_id: UUID) -> str:
    """One request, like one uvicorn worker. Returns "ok" or the error code."""
    try:
        TeamService._create_sync("Backend", user_id)
        return "ok"
    except AppError as e:
        return str(e.code)
    finally:
        connections.close_all()


async def test_parallel_creates_stop_at_10_teams(monkeypatch):
    user = await sync_to_async(User.objects.create_user)(
        email="ana@example.com", display_name="Ana Pop", password="correct horse battery"
    )
    for i in range(9):
        await TeamService.create(f"Team {i}", user.id)

    original = TeamRepository.count_created_by_sync
    calls = []

    def slow(user_id: UUID) -> int:
        count = original(user_id)
        if not calls:
            calls.append(user_id)
            time.sleep(0.5)  # the first request holds the lock while the second one starts
        return count

    monkeypatch.setattr(TeamRepository, "count_created_by_sync", staticmethod(slow))

    def both() -> list[str]:
        with ThreadPoolExecutor(2) as pool:
            a = pool.submit(create, user.id)
            time.sleep(0.15)
            b = pool.submit(create, user.id)
            return [a.result(), b.result()]

    results = await asyncio.to_thread(both)

    assert sorted(results) == ["ok", "team_limit_reached"]
    assert await Team.objects.filter(created_by=user).acount() == 10
