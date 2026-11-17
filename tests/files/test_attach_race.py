"""Attach at the same time as a delete or another attach of the same file: they lock the file
rows, so one waits for the other and a file is never both deleted and in a message."""

import pytest
from django.utils import timezone

from files.models import File
from files.repositories import FileRepository
from files.services import FileService
from shared.exceptions import Conflict, NotFound
from tests.helpers import hold_first_lock, make_file, run_overlapping

pytestmark = pytest.mark.django_db(transaction=True)


def hold_first_file_lock(monkeypatch) -> None:
    # attach locks with lock_many_sync, DELETE /files with lock_sync: the first of either waits
    hold_first_lock(monkeypatch, FileRepository, "lock_sync", "lock_many_sync")


async def test_attach_first_then_delete_is_refused(user, team, channel, monkeypatch):
    file = await make_file(user, "attachment", team)
    hold_first_file_lock(monkeypatch)

    started, waiting = await run_overlapping(
        lambda: FileService._attach_sync([file.id], user.id, channel.id, timezone.now()),
        lambda: FileService._delete_sync(file.id, user.id, timezone.now()),
    )

    started.result()
    with pytest.raises(Conflict) as error:
        waiting.result()
    assert error.value.code == "file_attached"
    saved = await File.objects.aget(id=file.id)
    assert saved.attached_at is not None and saved.deleted_at is None


async def test_delete_first_then_attach_is_not_found(user, team, channel, monkeypatch):
    file = await make_file(user, "attachment", team)
    hold_first_file_lock(monkeypatch)

    started, waiting = await run_overlapping(
        lambda: FileService._delete_sync(file.id, user.id, timezone.now()),
        lambda: FileService._attach_sync([file.id], user.id, channel.id, timezone.now()),
    )

    started.result()
    with pytest.raises(NotFound) as error:
        waiting.result()
    assert error.value.code == "file_not_found"
    saved = await File.objects.aget(id=file.id)
    assert saved.attached_at is None and saved.deleted_at is not None


async def test_two_attaches_of_the_same_file(user, team, channel, monkeypatch):
    """Two messages with the same file: the first one gets it."""
    file = await make_file(user, "attachment", team)
    other = await make_file(user, "attachment", team)
    hold_first_file_lock(monkeypatch)

    started, waiting = await run_overlapping(
        lambda: FileService._attach_sync([file.id], user.id, channel.id, timezone.now()),
        lambda: FileService._attach_sync([other.id, file.id], user.id, channel.id, timezone.now()),
    )

    assert [attached.id for attached in started.result()] == [file.id]
    with pytest.raises(Conflict) as error:
        waiting.result()
    assert error.value.code == "file_already_attached"
    assert error.value.fields == {"file_id": str(file.id)}
    assert (await File.objects.aget(id=other.id)).attached_at is None  # all or nothing
