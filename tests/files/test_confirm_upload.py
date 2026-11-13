"""POST /files/{file_id}/confirm against the real MinIO (D-15, D-18). In CI, needs-minio starts
MinIO and creates the bucket."""

from datetime import timedelta

import pytest
from django.conf import settings
from django.utils import timezone

from files.models import File
from shared import storage
from tests.helpers import (
    ELF,
    MACH_O,
    WINDOWS,
    headers_for,
    image_bytes,
    make_user,
    post_file,
    put_upload,
    zip_bytes,
)

pytestmark = pytest.mark.django_db(transaction=True)

PNG = image_bytes("PNG")


@pytest.fixture(autouse=True)
async def remove_objects():
    """Every object a test made: the uploads and the final keys of its files."""
    yield
    keys = [key async for key in File.objects.values_list("object_key", flat=True)]
    keys += [f"uploads/{file_id}" async for file_id in File.objects.values_list("id", flat=True)]
    storage.delete(*keys)


async def start_upload(client, auth, data: bytes, **changes) -> str:
    """Steps 1 and 2: POST /files for data, then the browser's PUT. Returns the file id."""
    body = (await post_file(client, auth, size=len(data), **changes)).json()
    assert put_upload(body["upload_url"], data, body["upload_headers"]) == 200
    return body["file_id"]


async def confirm(client, file_id, auth):
    return await client.post(f"/api/core/v1/files/{file_id}/confirm", headers=auth)


def put_object(key: str, data: bytes, content_type: str) -> None:
    """Write an object without the signed URL, to fake what a URL would refuse."""
    storage.internal_client().put_object(
        Bucket=settings.MINIO_BUCKET, Key=key, Body=data, ContentType=content_type
    )


async def assert_mismatch(client, file_id, auth) -> None:
    response = await confirm(client, file_id, auth)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "upload_mismatch"
    file = await File.objects.aget(id=file_id)
    assert file.deleted_at is not None
    assert storage.head(file.object_key) is None
    assert storage.head(f"uploads/{file_id}") is None


# --- status and shape ---


async def test_confirm_returns_the_ready_file(async_client, auth):
    file_id = await start_upload(async_client, auth, PNG)

    response = await confirm(async_client, file_id, auth)

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "id": file_id,
        "purpose": "avatar",
        "team_id": None,
        "filename": "me.png",
        "mime": "image/png",
        "size": len(PNG),
        "status": "ready",
        "created_at": body["created_at"],
    }


async def test_confirm_moves_the_upload_to_the_final_key(async_client, auth):
    file_id = await start_upload(async_client, auth, PNG)

    await confirm(async_client, file_id, auth)

    file = await File.objects.aget(id=file_id)
    assert file.status == File.Status.READY
    assert storage.read_all(file.object_key) == PNG
    assert storage.head(f"uploads/{file_id}") is None


@pytest.mark.parametrize(
    ("purpose", "data", "mime"),
    [
        ("team_icon", image_bytes("WEBP"), "image/webp"),
        ("attachment", b"%PDF-1.7\n" + b"x" * 100, "application/pdf"),
    ],
)
async def test_team_files(async_client, auth, team, purpose, data, mime):
    file_id = await start_upload(
        async_client, auth, data, purpose=purpose, team_id=str(team.id), mime=mime
    )

    response = await confirm(async_client, file_id, auth)

    assert response.status_code == 200
    assert response.json()["team_id"] == str(team.id)
    file = await File.objects.aget(id=file_id)
    assert storage.read_all(file.object_key) == data


@pytest.mark.parametrize(
    ("fmt", "mime"), [("JPEG", "image/jpeg"), ("WEBP", "image/webp"), ("GIF", "image/gif")]
)
async def test_each_image_type(async_client, auth, fmt, mime):
    file_id = await start_upload(async_client, auth, image_bytes(fmt), mime=mime)

    assert (await confirm(async_client, file_id, auth)).status_code == 200


async def test_confirm_twice_changes_nothing(async_client, auth):
    file_id = await start_upload(async_client, auth, PNG)
    first = await confirm(async_client, file_id, auth)

    second = await confirm(async_client, file_id, auth)

    assert second.status_code == 200
    assert second.json() == first.json()
    file = await File.objects.aget(id=file_id)
    assert storage.read_all(file.object_key) == PNG


async def test_upload_url_used_again_after_confirm_changes_nothing(async_client, auth):
    body = (await post_file(async_client, auth, size=len(PNG))).json()
    assert put_upload(body["upload_url"], PNG, body["upload_headers"]) == 200
    await confirm(async_client, body["file_id"], auth)
    other = image_bytes("PNG")  # another image, padded to the signed size
    other = (other + b"\0" * len(PNG))[: len(PNG)]

    assert put_upload(body["upload_url"], other, body["upload_headers"]) == 200

    file = await File.objects.aget(id=body["file_id"])
    assert storage.read_all(file.object_key) == PNG  # the final key isn't writable by the URL


# --- not found, not mine, expired, missing ---


async def test_unknown_file(async_client, auth):
    response = await confirm(async_client, "00000000-0000-0000-0000-000000000001", auth)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "file_not_found"


async def test_deleted_file(async_client, auth):
    file_id = await start_upload(async_client, auth, PNG)
    await File.objects.filter(id=file_id).aupdate(deleted_at=timezone.now())

    response = await confirm(async_client, file_id, auth)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "file_not_found"


async def test_someone_elses_file(async_client, auth):
    file_id = await start_upload(async_client, auth, PNG)
    other = await headers_for(await make_user("bob@example.com"))

    response = await confirm(async_client, file_id, other)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
    assert (await File.objects.aget(id=file_id)).status == File.Status.PENDING


async def test_needs_a_token(async_client, auth):
    file_id = await start_upload(async_client, auth, PNG)

    response = await async_client.post(f"/api/core/v1/files/{file_id}/confirm")

    assert response.status_code == 401


async def test_expired_upload(async_client, auth):
    file_id = await start_upload(async_client, auth, PNG)
    await File.objects.filter(id=file_id).aupdate(
        upload_expires_at=timezone.now() - timedelta(seconds=1)
    )

    response = await confirm(async_client, file_id, auth)

    assert response.status_code == 410
    assert response.json()["error"]["code"] == "upload_expired"
    assert (await File.objects.aget(id=file_id)).status == File.Status.PENDING


async def test_nothing_uploaded_yet(async_client, auth):
    body = (await post_file(async_client, auth, size=len(PNG))).json()

    response = await confirm(async_client, body["file_id"], auth)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "upload_missing"
    file = await File.objects.aget(id=body["file_id"])
    assert file.status == File.Status.PENDING and file.deleted_at is None


async def test_upload_after_upload_missing_then_confirm(async_client, auth):
    body = (await post_file(async_client, auth, size=len(PNG))).json()
    await confirm(async_client, body["file_id"], auth)  # upload_missing

    assert put_upload(body["upload_url"], PNG, body["upload_headers"]) == 200
    response = await confirm(async_client, body["file_id"], auth)

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


# --- the copy doesn't match step 1 ---


async def test_other_size_in_minio(async_client, auth):
    body = (await post_file(async_client, auth, size=len(PNG))).json()
    put_object(f"uploads/{body['file_id']}", PNG + b"!", "image/png")

    await assert_mismatch(async_client, body["file_id"], auth)


async def test_other_type_in_minio(async_client, auth):
    body = (await post_file(async_client, auth, size=len(PNG))).json()
    put_object(f"uploads/{body['file_id']}", PNG, "image/gif")

    await assert_mismatch(async_client, body["file_id"], auth)


@pytest.mark.parametrize(
    "data",
    [
        b"%PDF-1.7\n" + b"x" * 100,  # a PDF
        b"just some text, not an image at all",
        image_bytes("JPEG"),  # a real image, but not the declared PNG
        image_bytes("PNG", (256, 256))[:300],  # a PNG cut short
    ],
)
async def test_avatar_that_isnt_the_declared_png(async_client, auth, data):
    file_id = await start_upload(async_client, auth, data)

    await assert_mismatch(async_client, file_id, auth)


@pytest.mark.parametrize("program", [WINDOWS, ELF, MACH_O])
async def test_program_attachment(async_client, auth, team, program):
    file_id = await start_upload(
        async_client,
        auth,
        program,
        purpose="attachment",
        team_id=str(team.id),
        filename="report.pdf",
        mime="application/pdf",
    )

    await assert_mismatch(async_client, file_id, auth)


async def test_attachment_content_isnt_compared_with_its_type(async_client, auth, team):
    # a .docx is a zip; only programs are refused (D-18)
    file_id = await start_upload(
        async_client,
        auth,
        zip_bytes(),
        purpose="attachment",
        team_id=str(team.id),
        filename="report.docx",
        mime="application/pdf",
    )

    assert (await confirm(async_client, file_id, auth)).status_code == 200


async def test_rejected_file_cant_be_confirmed_again(async_client, auth):
    file_id = await start_upload(async_client, auth, b"not an image")
    await confirm(async_client, file_id, auth)

    response = await confirm(async_client, file_id, auth)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "file_not_found"
