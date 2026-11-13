"""FileRepository.mark_ready and mark_deleted: the status changes confirm makes."""

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from files.models import File
from files.repositories import FileRepository

pytestmark = pytest.mark.django_db(transaction=True)


async def pending_file(owner) -> File:
    file_id = uuid.uuid4()
    return await File.objects.acreate(
        id=file_id,
        owner=owner,
        purpose=File.Purpose.AVATAR,
        object_key=f"avatars/{owner.id}/{file_id}",
        filename="me.png",
        mime="image/png",
        size=5,
        upload_expires_at=timezone.now() + timedelta(minutes=10),
    )


async def test_mark_ready(user):
    file = await pending_file(user)

    assert await FileRepository.mark_ready(file.id) is True
    assert (await File.objects.aget(id=file.id)).status == File.Status.READY


async def test_mark_ready_twice_changes_it_once(user):
    file = await pending_file(user)
    await FileRepository.mark_ready(file.id)

    assert await FileRepository.mark_ready(file.id) is False


async def test_deleted_file_isnt_marked_ready(user):
    file = await pending_file(user)
    await FileRepository.mark_deleted(file.id, timezone.now())

    assert await FileRepository.mark_ready(file.id) is False
    assert (await File.objects.aget(id=file.id)).status == File.Status.PENDING


async def test_mark_deleted_keeps_the_first_time(user):
    file = await pending_file(user)
    first = timezone.now() - timedelta(minutes=1)
    await FileRepository.mark_deleted(file.id, first)

    await FileRepository.mark_deleted(file.id, timezone.now())

    assert (await File.objects.aget(id=file.id)).deleted_at == first


async def test_get(user):
    file = await pending_file(user)

    found = await FileRepository.get(file.id)

    assert found is not None and found.id == file.id
    assert await FileRepository.get(uuid.uuid4()) is None
