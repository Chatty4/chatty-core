"""POST /internal/files/detach: the attachments of a deleted or unsaved message are deleted
(D-03). Safe to retry: it always answers 204."""

import uuid

import pytest
from django.conf import settings
from django.utils import timezone

from files.models import File
from tests.helpers import make_file

pytestmark = pytest.mark.django_db(transaction=True)

SERVICE = {"X-Service-Token": settings.CORE_SERVICE_TOKEN}


async def detach(client, *files, headers: dict = SERVICE):
    body = {"file_ids": [str(getattr(file, "id", file)) for file in files]}
    return await client.post(
        "/internal/files/detach", body, content_type="application/json", headers=headers
    )


async def attached_file(user, team) -> File:
    return await make_file(user, "attachment", team, attached_at=timezone.now())


# --- detached ---


async def test_detach_attached_files(async_client, user, team):
    files = [await attached_file(user, team), await attached_file(user, team)]

    response = await detach(async_client, *files)

    assert response.status_code == 204
    assert response.content == b""
    for file in files:
        saved = await File.objects.aget(id=file.id)
        assert saved.attached_at is None
        assert saved.deleted_at is not None


async def test_detach_twice_keeps_the_first_time(async_client, user, team):
    file = await attached_file(user, team)
    await detach(async_client, file)
    first = (await File.objects.aget(id=file.id)).deleted_at

    response = await detach(async_client, file)

    assert response.status_code == 204
    assert (await File.objects.aget(id=file.id)).deleted_at == first


async def test_unknown_and_deleted_files_are_skipped(async_client, user, team):
    deleted_at = timezone.now()
    deleted = await make_file(user, "attachment", team, deleted_at=deleted_at)
    file = await attached_file(user, team)

    response = await detach(async_client, uuid.uuid4(), deleted, file)

    assert response.status_code == 204
    assert (await File.objects.aget(id=file.id)).deleted_at is not None  # the others still are
    assert (await File.objects.aget(id=deleted.id)).deleted_at == deleted_at


@pytest.mark.parametrize("purpose", ["avatar", "team_icon"])
async def test_avatars_and_team_icons_are_skipped(async_client, user, team, purpose):
    file = await make_file(user, purpose, team if purpose == "team_icon" else None)

    response = await detach(async_client, file)

    assert response.status_code == 204
    assert (await File.objects.aget(id=file.id)).deleted_at is None


async def test_detach_then_attach_is_not_found(async_client, user, team, channel):
    file = await make_file(user, "attachment", team)
    body = {"user_id": str(user.id), "channel_id": str(channel.id), "file_ids": [str(file.id)]}
    attach = await async_client.post(
        "/internal/files/attach", body, content_type="application/json", headers=SERVICE
    )
    assert attach.status_code == 200

    await detach(async_client, file)
    again = await async_client.post(
        "/internal/files/attach", body, content_type="application/json", headers=SERVICE
    )

    assert again.status_code == 404
    assert again.json()["error"]["code"] == "file_not_found"


# --- request and token ---


@pytest.mark.parametrize(
    ("body", "fields"),
    [
        ({"file_ids": []}, {"file_ids": "too_short"}),
        ({"file_ids": [str(uuid.uuid4()) for _ in range(11)]}, {"file_ids": "too_long"}),
        ({"file_ids": ["6f1c2a9e-0000-4000-8000-000000000001"] * 2}, {"file_ids": "invalid"}),
        ({"file_ids": ["not-a-uuid"]}, {"file_ids.0": "invalid"}),
        ({}, {"file_ids": "required"}),
    ],
    ids=["empty", "eleven", "duplicate", "not_a_uuid", "missing"],
)
async def test_invalid_file_ids(async_client, body, fields):
    response = await async_client.post(
        "/internal/files/detach", body, content_type="application/json", headers=SERVICE
    )

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["fields"] == fields


@pytest.mark.parametrize("token", [None, "wrong"])
async def test_service_token_is_needed(async_client, user, team, token):
    file = await attached_file(user, team)
    headers = {} if token is None else {"X-Service-Token": token}

    response = await detach(async_client, file, headers=headers)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_service_token"
    assert (await File.objects.aget(id=file.id)).deleted_at is None
