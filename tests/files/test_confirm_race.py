"""Two confirms of one file at once: one marks it ready, the other answers with what it left."""

import asyncio

import pytest
from django.utils import timezone

from files.models import File
from files.repositories import FileRepository
from files.services import FileService
from shared import storage
from shared.exceptions import NotFound
from tests.helpers import image_bytes, post_file, put_upload

pytestmark = pytest.mark.django_db(transaction=True)

PNG = image_bytes("PNG")


@pytest.fixture
async def uploaded(async_client, auth):
    """A pending file with its upload in MinIO; its objects are removed afterwards."""
    body = (await post_file(async_client, auth, size=len(PNG))).json()
    assert put_upload(body["upload_url"], PNG, body["upload_headers"]) == 200
    file = await File.objects.aget(id=body["file_id"])
    yield file
    storage.delete(file.object_key, f"uploads/{file.id}")


async def test_parallel_confirms_mark_it_ready_once(uploaded, user, monkeypatch):
    original_matches = FileService._copy_matches
    original_mark_ready = FileRepository.mark_ready
    both_checked = asyncio.Barrier(2)
    marked: list[bool] = []

    async def wait_for_the_other(file: File) -> bool:
        matches = await original_matches(file)
        await both_checked.wait()  # both pass the checks before either marks the file ready
        return matches

    async def record(file_id) -> bool:
        changed = await original_mark_ready(file_id)
        marked.append(changed)
        return changed

    monkeypatch.setattr(FileService, "_copy_matches", staticmethod(wait_for_the_other))
    monkeypatch.setattr(FileRepository, "mark_ready", staticmethod(record))

    results = await asyncio.gather(
        FileService.confirm(uploaded.id, user.id),
        FileService.confirm(uploaded.id, user.id),
    )

    assert sorted(marked) == [False, True]  # one changed the row, the other found it ready
    assert [file.status for file in results] == [File.Status.READY, File.Status.READY]
    file = await File.objects.aget(id=uploaded.id)
    assert file.status == File.Status.READY and file.deleted_at is None
    assert storage.read_all(file.object_key) == PNG


async def test_file_deleted_while_checking_is_not_found(uploaded, user, monkeypatch):
    original_matches = FileService._copy_matches

    async def deleted_meanwhile(file: File) -> bool:
        matches = await original_matches(file)
        await FileRepository.mark_deleted(file.id, timezone.now())  # e.g. by another confirm
        return matches

    monkeypatch.setattr(FileService, "_copy_matches", staticmethod(deleted_meanwhile))

    with pytest.raises(NotFound):
        await FileService.confirm(uploaded.id, user.id)

    assert (await File.objects.aget(id=uploaded.id)).status == File.Status.PENDING
