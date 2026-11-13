import asyncio
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from uuid import UUID

import pytest
from asgiref.sync import sync_to_async
from django.db import connections
from django.utils import timezone

from files.models import File
from files.repositories import FileRepository
from files.services import MAX_PENDING_UPLOADS, FileService
from shared.exceptions import AppError
from tests.helpers import make_user

pytestmark = pytest.mark.django_db(transaction=True)


def create(user_id: UUID) -> str:
    """One request, like one uvicorn worker. Returns "ok" or the error code."""
    file_id = uuid.uuid4()
    try:
        FileService._create_upload_sync(
            file_id,
            owner_id=user_id,
            team_id=None,
            purpose=File.Purpose.AVATAR,
            object_key=f"avatars/{user_id}/{file_id}",
            filename="me.png",
            mime="image/png",
            size=5,
            now=timezone.now(),
        )
        return "ok"
    except AppError as e:
        return str(e.code)
    finally:
        connections.close_all()


async def test_parallel_uploads_stop_at_the_cap(monkeypatch):
    user = await make_user("ana@example.com")
    for _ in range(MAX_PENDING_UPLOADS - 1):
        await sync_to_async(create)(user.id)

    original = FileRepository.count_pending_sync
    calls = []

    def slow(owner_id: UUID, now: datetime) -> int:
        count = original(owner_id, now)
        if not calls:
            calls.append(owner_id)
            time.sleep(0.5)  # the first request holds the lock while the second one starts
        return count

    monkeypatch.setattr(FileRepository, "count_pending_sync", staticmethod(slow))

    def both() -> list[str]:
        with ThreadPoolExecutor(2) as pool:
            a = pool.submit(create, user.id)
            time.sleep(0.15)
            b = pool.submit(create, user.id)
            return [a.result(), b.result()]

    results = await asyncio.to_thread(both)

    assert sorted(results) == ["ok", "rate_limited"]
    assert await File.objects.filter(owner_id=user.id).acount() == MAX_PENDING_UPLOADS
