"""PUT /me and DELETE of the same file at once: both lock the file row, so one waits for the
other and the profile never points at a deleted file."""

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import connections
from django.utils import timezone

from files.models import File
from files.repositories import FileRepository
from files.services import FileService
from shared.exceptions import BadRequest
from tests.helpers import make_file
from users.models import User
from users.services import UserService

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.usefixtures("remove_objects")]


def slow_first_lock(monkeypatch) -> None:
    """The first lock_sync holds the row for a while, so the second call starts meanwhile."""
    original = FileRepository.lock_sync
    calls = []

    def slow(file_id):
        file = original(file_id)
        if not calls:
            calls.append(file_id)
            time.sleep(0.5)
        return file

    monkeypatch.setattr(FileRepository, "lock_sync", staticmethod(slow))


async def run_in_order(first, second) -> tuple:
    """Each call in its own thread and connection, like two uvicorn workers; first starts first."""

    def call(fn):
        try:
            return fn()
        finally:
            connections.close_all()

    def run():
        with ThreadPoolExecutor(2) as pool:
            started = pool.submit(call, first)
            time.sleep(0.15)
            waiting = pool.submit(call, second)
            return started, waiting

    started, waiting = await asyncio.to_thread(run)
    return started, waiting


async def test_put_first_then_delete_removes_the_avatar(user, monkeypatch):
    file = await make_file(user)
    slow_first_lock(monkeypatch)

    started, waiting = await run_in_order(
        lambda: UserService._update_profile_sync(user, "Ana Pop", "UTC", file.id),
        lambda: FileService._delete_sync(file.id, user.id, timezone.now()),
    )

    started.result()
    waiting.result()
    assert (await User.objects.aget(id=user.id)).avatar_id is None
    assert (await File.objects.aget(id=file.id)).deleted_at is not None


async def test_delete_first_then_put_is_refused(user, monkeypatch):
    file = await make_file(user)
    slow_first_lock(monkeypatch)

    started, waiting = await run_in_order(
        lambda: FileService._delete_sync(file.id, user.id, timezone.now()),
        lambda: UserService._update_profile_sync(user, "Ana Pop", "UTC", file.id),
    )

    started.result()
    with pytest.raises(BadRequest) as error:
        waiting.result()
    assert error.value.code == "invalid_file"
    assert (await User.objects.aget(id=user.id)).avatar_id is None
    assert (await File.objects.aget(id=file.id)).deleted_at is not None
