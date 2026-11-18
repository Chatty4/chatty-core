"""clean_up_files (D-17): unused files leave MinIO and the database; used ones stay."""

from datetime import timedelta

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from files.models import File
from files.services import FileService
from shared import storage
from teams.models import Team
from tests.helpers import image_bytes, make_file

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.usefixtures("remove_objects")]

PNG = image_bytes("PNG")


async def clean_up() -> tuple[int, int]:
    return await sync_to_async(FileService.clean_up)(timezone.now())


async def age(file: File, hours: int) -> None:
    """created_at is auto_now_add, so it can only be moved back with an update."""
    await File.objects.filter(id=file.id).aupdate(
        created_at=timezone.now() - timedelta(hours=hours)
    )


async def assert_gone(file: File) -> None:
    assert not await File.objects.filter(id=file.id).aexists()
    assert storage.head(file.object_key) is None


async def assert_kept(file: File) -> None:
    assert (await File.objects.aget(id=file.id)).deleted_at is None
    assert storage.head(file.object_key) is not None


# --- kept ---


async def test_attached_file_is_kept(user, team):
    file = await make_file(user, "attachment", team, PNG, attached_at=timezone.now())
    await age(file, 48)
    await clean_up()
    await assert_kept(file)


async def test_new_unsent_attachment_is_kept(user, team):
    file = await make_file(user, "attachment", team, PNG)
    await age(file, 23)
    await clean_up()
    await assert_kept(file)


async def test_current_avatar_and_icon_are_kept(user, team):
    avatar = await make_file(user, "avatar", data=PNG)
    icon = await make_file(user, "team_icon", team, PNG)
    user.avatar = avatar
    await user.asave(update_fields=["avatar"])
    team.icon = icon
    await team.asave(update_fields=["icon"])
    await age(avatar, 48)
    await age(icon, 48)

    await clean_up()

    await assert_kept(avatar)
    await assert_kept(icon)


# --- removed ---


async def test_old_unsent_attachment_is_removed(user, team):
    file = await make_file(user, "attachment", team, PNG)
    await age(file, 25)
    assert await clean_up() == (1, 1)
    await assert_gone(file)


async def test_replaced_avatar_is_removed(user):
    old = await make_file(user, "avatar", data=PNG)
    new = await make_file(user, "avatar", data=PNG)
    user.avatar = new
    await user.asave(update_fields=["avatar"])
    await age(old, 48)
    await age(new, 48)

    await clean_up()

    await assert_gone(old)
    await assert_kept(new)


async def test_expired_pending_upload_is_removed(user, team):
    file = await make_file(
        user,
        "attachment",
        team,
        status=File.Status.PENDING,
        upload_expires_at=timezone.now() - timedelta(hours=2),
    )
    await clean_up()
    assert not await File.objects.filter(id=file.id).aexists()


async def test_file_marked_deleted_is_removed(user, team):
    file = await make_file(user, "attachment", team, PNG, deleted_at=timezone.now())
    assert await clean_up() == (0, 1)
    await assert_gone(file)


async def test_files_of_a_deleted_team_are_removed(user, team):
    icon = await make_file(user, "team_icon", team, PNG)
    sent = await make_file(user, "attachment", team, PNG, attached_at=timezone.now())
    team.icon = icon
    team.deleted_at = timezone.now()
    await team.asave(update_fields=["icon", "deleted_at"])

    other_team = await Team.objects.acreate(name="Frontend", created_by=user)
    other_sent = await make_file(user, "attachment", other_team, PNG, attached_at=timezone.now())

    await clean_up()

    await assert_gone(icon)
    await assert_gone(sent)
    await assert_kept(other_sent)


# --- MinIO fails ---


async def test_rows_stay_when_minio_fails(user, team, monkeypatch):
    file = await make_file(user, "attachment", team, PNG, deleted_at=timezone.now())

    def fail(*keys):
        raise RuntimeError("MinIO is down")

    with monkeypatch.context() as patch:
        patch.setattr(storage, "delete", fail)
        with pytest.raises(RuntimeError):
            await clean_up()

    assert await File.objects.filter(id=file.id).aexists()
