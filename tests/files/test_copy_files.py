import uuid

import pytest
from botocore.exceptions import EndpointConnectionError
from django.conf import settings
from django.db import connection
from django.utils import timezone

from files.models import File
from shared import storage
from teams.models import Team
from tests.helpers import make_file, make_user

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.usefixtures("remove_objects")]

SERVICE = {"X-Service-Token": settings.CORE_SERVICE_TOKEN}
PDF = b"%PDF-1.7 report"


async def copy(client, user, channel_id, *files, headers: dict = SERVICE):
    body = {
        "user_id": str(user.id),
        "channel_id": str(channel_id),
        "file_ids": [str(getattr(file, "id", file)) for file in files],
    }
    return await client.post(
        "/internal/files/copy", body, content_type="application/json", headers=headers
    )


async def assert_error(response, status: int, code: str, file_id=None) -> None:
    assert response.status_code == status
    error = response.json()["error"]
    assert error["code"] == code
    if file_id is not None:
        assert error["fields"] == {"file_id": str(file_id)}


async def sent_file(user, team, data: bytes = PDF, **changes) -> File:
    """An attachment that is in a message, with its object in MinIO."""
    fields = {"filename": "report.pdf", "mime": "application/pdf", "attached_at": timezone.now()}
    return await make_file(user, "attachment", team, data, **(fields | changes))


@pytest.fixture
async def bob():
    """Who forwards the message; he didn't upload the files."""
    return await make_user("bob@example.com")


# --- copied ---


async def test_copy_two_files(async_client, user, team, channel, bob):
    report = await sent_file(user, team)
    chart = await sent_file(user, team, b"chart", filename="chart.png", mime="image/png")

    response = await copy(async_client, bob, channel.id, chart, report)

    assert response.status_code == 200
    attachments = response.json()["attachments"]
    assert len(attachments) == 2
    for source, entry in zip((chart, report), attachments, strict=True):  # the order of file_ids
        new = await File.objects.aget(id=entry["file_id"])
        assert new.id != source.id
        assert entry == {
            "file_id": str(new.id),
            "object_key": f"attachments/{team.id}/{new.id}",
            "filename": source.filename,
            "mime": source.mime,
            "size": source.size,
            "attached_at": entry["attached_at"],
        }
        assert new.owner_id == bob.id and new.team_id == team.id
        assert new.status == File.Status.READY and new.attached_at is not None
        assert storage.read_all(new.object_key) == storage.read_all(source.object_key)

        unchanged = await File.objects.aget(id=source.id)
        assert unchanged.attached_at == source.attached_at and unchanged.deleted_at is None


async def test_copy_outlives_its_source(async_client, user, team, channel, bob):
    source = await sent_file(user, team)
    new_id = (await copy(async_client, bob, channel.id, source)).json()["attachments"][0]["file_id"]

    await async_client.post(
        "/internal/files/detach",
        {"file_ids": [str(source.id)]},
        content_type="application/json",
        headers=SERVICE,
    )

    new = await File.objects.aget(id=new_id)
    assert new.attached_at is not None and new.deleted_at is None


# --- each check creates nothing ---


async def bad_source(kind: str, user, team):
    """A file that fails exactly one check, or an unknown id."""
    if kind == "unknown":
        return uuid.uuid4()
    if kind == "avatar":
        return await make_file(user)
    if kind == "team_icon":
        return await make_file(user, "team_icon", team)
    if kind == "other_team":
        return await sent_file(user, await Team.objects.acreate(name="Design", created_by=user))
    changes = {
        "deleted": {"deleted_at": timezone.now()},
        "not_attached": {"attached_at": None},
        "pending": {"status": File.Status.PENDING, "attached_at": None},
    }[kind]
    return await sent_file(user, team, **changes)


@pytest.mark.parametrize(
    ("kind", "status", "code"),
    [
        ("unknown", 404, "file_not_found"),
        ("deleted", 404, "file_not_found"),
        ("avatar", 400, "wrong_purpose"),
        ("team_icon", 400, "wrong_purpose"),
        ("other_team", 400, "wrong_team"),
        ("not_attached", 409, "file_not_attached"),
        ("pending", 409, "file_not_attached"),
    ],
)
async def test_each_check_creates_nothing(
    async_client, user, team, channel, bob, kind, status, code
):
    good = await sent_file(user, team)
    bad = await bad_source(kind, user, team)
    before = await File.objects.acount()

    response = await copy(async_client, bob, channel.id, good, bad)

    await assert_error(response, status, code, getattr(bad, "id", bad))
    assert await File.objects.acount() == before


async def test_checks_run_in_order(async_client, user, team, channel, bob):
    other = await Team.objects.acreate(name="Design", created_by=user)
    unsent_of_other_team = await sent_file(user, other, attached_at=None)

    response = await copy(async_client, bob, channel.id, unsent_of_other_team)

    await assert_error(response, 400, "wrong_team", unsent_of_other_team.id)  # check 3 before 4


# --- the channel ---


async def test_unknown_channel(async_client, user, team, bob):
    response = await copy(async_client, bob, uuid.uuid4(), await sent_file(user, team))

    await assert_error(response, 404, "channel_not_found")


async def test_channel_of_a_deleted_team(async_client, user, team, channel, bob):
    source = await sent_file(user, team)
    await Team.objects.filter(id=team.id).aupdate(deleted_at=timezone.now())

    response = await copy(async_client, bob, channel.id, source)

    await assert_error(response, 404, "channel_not_found")


# --- during the copy ---


async def test_minio_failure_leaves_nothing(async_client, user, team, channel, bob, monkeypatch):
    first, second = await sent_file(user, team), await sent_file(user, team)
    real_copy, copied = storage.copy, []

    def copy_then_fail(source: str, target: str) -> None:
        if copied:
            raise EndpointConnectionError(endpoint_url=settings.MINIO_INTERNAL_URL)
        real_copy(source, target)
        copied.append(target)

    monkeypatch.setattr(storage, "copy", copy_then_fail)
    before = await File.objects.acount()

    response = await copy(async_client, bob, channel.id, first, second)

    await assert_error(response, 503, "storage_unavailable")
    assert await File.objects.acount() == before
    assert storage.head(copied[0]) is None


async def test_source_deleted_during_the_copy(async_client, user, team, channel, bob, monkeypatch):
    source = await sent_file(user, team)
    real_copy, copied = storage.copy, []

    def copy_then_detach(source_key: str, target: str) -> None:
        real_copy(source_key, target)
        copied.append(target)
        # the message is deleted meanwhile; this thread has its own connection
        File.objects.filter(id=source.id).update(attached_at=None, deleted_at=timezone.now())
        connection.close()

    monkeypatch.setattr(storage, "copy", copy_then_detach)
    before = await File.objects.acount()

    response = await copy(async_client, bob, channel.id, source)

    await assert_error(response, 404, "file_not_found", source.id)
    assert await File.objects.acount() == before
    assert storage.head(copied[0]) is None


# --- token ---


@pytest.mark.parametrize("token", [None, "wrong"])
async def test_service_token_is_needed(async_client, user, team, channel, bob, token):
    headers = {} if token is None else {"X-Service-Token": token}

    response = await copy(
        async_client, bob, channel.id, await sent_file(user, team), headers=headers
    )

    await assert_error(response, 401, "invalid_service_token")
