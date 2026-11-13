"""The browser's step 2 against the real MinIO: the URL from POST /files accepts exactly the file
that was announced (D-15). In CI, needs-minio starts MinIO and creates the bucket."""

import pytest
from django.conf import settings

from shared import storage
from tests.helpers import post_file, put_upload

pytestmark = pytest.mark.django_db(transaction=True)

BODY = b"hello"  # 5 bytes, the size in AVATAR_UPLOAD


@pytest.fixture
async def upload(async_client, auth):
    body = (await post_file(async_client, auth)).json()
    yield body
    storage.internal_client().delete_object(
        Bucket=settings.MINIO_BUCKET, Key=f"uploads/{body['file_id']}"
    )


async def test_put_with_the_returned_headers_lands_in_uploads(upload):
    assert put_upload(upload["upload_url"], BODY, upload["upload_headers"]) == 200

    head = storage.internal_client().head_object(
        Bucket=settings.MINIO_BUCKET, Key=f"uploads/{upload['file_id']}"
    )
    assert head["ContentLength"] == len(BODY)
    assert head["ContentType"] == "image/png"


async def test_put_with_another_type_is_refused(upload):
    headers = upload["upload_headers"] | {"Content-Type": "image/gif"}

    assert put_upload(upload["upload_url"], BODY, headers) == 403


async def test_put_with_another_size_is_refused(upload):
    headers = {"Content-Type": "image/png"}  # urllib sets Content-Length from the body

    assert put_upload(upload["upload_url"], BODY + b"!", headers) == 403
