"""The browser's step 2 against the real MinIO: the URL from POST /files accepts exactly the file
that was announced (D-15). In CI, needs-minio starts MinIO and creates the bucket."""

import urllib.error
import urllib.request
from urllib.parse import urlsplit

import pytest
from django.conf import settings

from shared import storage
from tests.helpers import post_file

pytestmark = pytest.mark.django_db(transaction=True)

BODY = b"hello"  # 5 bytes, the size in AVATAR_UPLOAD


@pytest.fixture
async def upload(async_client, auth):
    body = (await post_file(async_client, auth)).json()
    yield body
    storage.internal_client().delete_object(
        Bucket=settings.MINIO_BUCKET, Key=f"uploads/{body['file_id']}"
    )


def put(url: str, data: bytes, headers: dict) -> int:
    """PUT like the browser does. The URL is signed for the public address (D-16), which in the
    core container is the container itself, so the request goes to MinIO's internal address with
    the signed address as Host: MinIO checks the signature against Host, as behind a proxy."""
    signed = urlsplit(url)
    internal = urlsplit(settings.MINIO_INTERNAL_URL)
    request = urllib.request.Request(
        signed._replace(scheme=internal.scheme, netloc=internal.netloc).geturl(),
        data=data,
        method="PUT",
        headers=headers | {"Host": signed.netloc},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status
    except urllib.error.HTTPError as e:
        return e.code


async def test_put_with_the_returned_headers_lands_in_uploads(upload):
    assert put(upload["upload_url"], BODY, upload["upload_headers"]) == 200

    head = storage.internal_client().head_object(
        Bucket=settings.MINIO_BUCKET, Key=f"uploads/{upload['file_id']}"
    )
    assert head["ContentLength"] == len(BODY)
    assert head["ContentType"] == "image/png"


async def test_put_with_another_type_is_refused(upload):
    headers = upload["upload_headers"] | {"Content-Type": "image/gif"}

    assert put(upload["upload_url"], BODY, headers) == 403


async def test_put_with_another_size_is_refused(upload):
    headers = {"Content-Type": "image/png"}  # urllib sets Content-Length from the body

    assert put(upload["upload_url"], BODY + b"!", headers) == 403
