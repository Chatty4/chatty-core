"""PUT /me and DELETE of the same file at once: both lock the file row, so one waits for the
other and the profile never points at a deleted file."""

import pytest
from django.utils import timezone

from files.models import File
from files.repositories import FileRepository
from files.services import FileService
from shared.exceptions import BadRequest
from tests.helpers import hold_first_lock, make_file, run_overlapping
from users.models import User
from users.services import UserService

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.usefixtures("remove_objects")]


async def test_put_first_then_delete_removes_the_avatar(user, monkeypatch):
    file = await make_file(user)
    hold_first_lock(monkeypatch, FileRepository, "lock_sync")

    started, waiting = await run_overlapping(
        lambda: UserService._update_profile_sync(user, "Ana Pop", "UTC", file.id),
        lambda: FileService._delete_sync(file.id, user.id, timezone.now()),
    )

    started.result()
    waiting.result()
    assert (await User.objects.aget(id=user.id)).avatar_id is None
    assert (await File.objects.aget(id=file.id)).deleted_at is not None


async def test_delete_first_then_put_is_refused(user, monkeypatch):
    file = await make_file(user)
    hold_first_lock(monkeypatch, FileRepository, "lock_sync")

    started, waiting = await run_overlapping(
        lambda: FileService._delete_sync(file.id, user.id, timezone.now()),
        lambda: UserService._update_profile_sync(user, "Ana Pop", "UTC", file.id),
    )

    started.result()
    with pytest.raises(BadRequest) as error:
        waiting.result()
    assert error.value.code == "invalid_file"
    assert (await User.objects.aget(id=user.id)).avatar_id is None
    assert (await File.objects.aget(id=file.id)).deleted_at is not None
