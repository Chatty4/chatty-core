"""DELETE /files/{file_id}: my own file in no message; the row stays for the cleanup job."""

import logging
import uuid

import pytest
from django.utils import timezone

from files.models import File
from files.services import MAX_PENDING_UPLOADS
from shared import storage
from tests.helpers import headers_for, image_bytes, make_file, make_user, post_file, put_upload

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.usefixtures("remove_objects")]

PNG = image_bytes("PNG")


async def delete(client, file_id, headers: dict):
    return await client.delete(f"/api/core/v1/files/{file_id}", headers=headers)


async def assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


async def assert_unchanged(file: File) -> None:
    assert (await File.objects.aget(id=file.id)).deleted_at is None
    assert storage.head(file.object_key) is not None


# --- deleted ---


async def test_delete_my_pending_file(async_client, auth):
    body = (await post_file(async_client, auth, size=len(PNG))).json()
    assert put_upload(body["upload_url"], PNG, body["upload_headers"]) == 200

    response = await delete(async_client, body["file_id"], auth)

    assert response.status_code == 204
    assert response.content == b""
    assert (await File.objects.aget(id=body["file_id"])).deleted_at is not None
    assert storage.head(f"uploads/{body['file_id']}") is None


async def test_deleted_upload_no_longer_counts_towards_the_cap(async_client, user, auth):
    pending = [
        await make_file(user, status=File.Status.PENDING) for _ in range(MAX_PENDING_UPLOADS)
    ]
    assert (await post_file(async_client, auth)).status_code == 429

    assert (await delete(async_client, pending[0].id, auth)).status_code == 204

    assert (await post_file(async_client, auth)).status_code == 201


async def test_delete_my_ready_file(async_client, user, auth):
    file = await make_file(user, data=PNG)

    response = await delete(async_client, file.id, auth)

    assert response.status_code == 204
    assert (await File.objects.aget(id=file.id)).deleted_at is not None
    assert storage.head(file.object_key) is None
    download = await async_client.get(f"/api/core/v1/files/{file.id}", headers=auth)
    await assert_error(download, 404, "file_not_found")
    confirm = await async_client.post(f"/api/core/v1/files/{file.id}/confirm", headers=auth)
    await assert_error(confirm, 404, "file_not_found")


async def test_delete_twice(async_client, user, auth):
    file = await make_file(user)
    await delete(async_client, file.id, auth)

    response = await delete(async_client, file.id, auth)

    await assert_error(response, 404, "file_not_found")


# --- refused ---


async def test_someone_elses_file(async_client, user):
    file = await make_file(user, data=PNG)
    other = await headers_for(await make_user("bob@example.com"))

    response = await delete(async_client, file.id, other)

    await assert_error(response, 403, "forbidden")
    await assert_unchanged(file)


async def test_unknown_file(async_client, auth):
    response = await delete(async_client, uuid.uuid4(), auth)

    await assert_error(response, 404, "file_not_found")


async def test_without_token(async_client, user):
    file = await make_file(user)

    response = await delete(async_client, file.id, {})

    assert response.status_code == 401


async def test_file_in_a_message(async_client, user, auth, team):
    file = await make_file(user, "attachment", team, data=PNG, attached_at=timezone.now())

    response = await delete(async_client, file.id, auth)

    await assert_error(response, 409, "file_attached")
    await assert_unchanged(file)


# --- MinIO ---


async def test_minio_error_still_deletes_the_file(async_client, user, auth, monkeypatch, caplog):
    file = await make_file(user)

    def unavailable(*keys: str) -> None:
        raise RuntimeError("MinIO is down")

    # only for the request: remove_objects needs the real delete afterwards
    with monkeypatch.context() as patch, caplog.at_level(logging.ERROR, logger="files.services"):
        patch.setattr(storage, "delete", unavailable)
        response = await delete(async_client, file.id, auth)

    assert response.status_code == 204
    assert (await File.objects.aget(id=file.id)).deleted_at is not None  # the cleanup job's turn
    assert f"Failed to delete the objects of file {file.id}" in caplog.text
