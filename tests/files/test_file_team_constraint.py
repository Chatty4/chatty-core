import uuid
from datetime import timedelta

import pytest
from django.db import IntegrityError
from django.utils import timezone

from files.models import File

pytestmark = pytest.mark.django_db(transaction=True)


async def new_file(owner, purpose: str, team) -> File:
    file_id = uuid.uuid4()
    return await File.objects.acreate(
        id=file_id,
        owner=owner,
        team=team,
        purpose=purpose,
        object_key=f"test/{file_id}",
        filename="a.png",
        mime="image/png",
        size=5,
        upload_expires_at=timezone.now() + timedelta(minutes=10),
    )


async def test_avatar_has_no_team(user, team):
    with pytest.raises(IntegrityError):
        await new_file(user, File.Purpose.AVATAR, team)


@pytest.mark.parametrize("purpose", [File.Purpose.TEAM_ICON, File.Purpose.ATTACHMENT])
async def test_team_files_need_a_team(user, purpose):
    with pytest.raises(IntegrityError):
        await new_file(user, purpose, None)


async def test_valid_rows_are_saved(user, team):
    await new_file(user, File.Purpose.AVATAR, None)
    await new_file(user, File.Purpose.ATTACHMENT, team)

    assert await File.objects.acount() == 2
