import uuid
from urllib.parse import parse_qs, urlsplit

import pytest
from django.conf import settings

from shared import storage


@pytest.fixture(autouse=True)
def fresh_clients():
    # the clients are cached; a test that changes settings must not see an old one
    storage.internal_client.cache_clear()
    storage.public_client.cache_clear()
    yield
    storage.internal_client.cache_clear()
    storage.public_client.cache_clear()


def test_presign_put_signs_type_size_and_host():
    url = urlsplit(storage.presign_put("uploads/abc", "image/png", 5))
    query = parse_qs(url.query)

    assert url.path == f"/{settings.MINIO_BUCKET}/uploads/abc"  # path style
    assert query["X-Amz-SignedHeaders"] == ["content-length;content-type;host"]
    assert query["X-Amz-Expires"] == [str(storage.UPLOAD_URL_SECONDS)]
    assert query["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]


def test_presign_put_takes_another_expiry():
    query = parse_qs(urlsplit(storage.presign_put("uploads/abc", "image/png", 5, 30)).query)

    assert query["X-Amz-Expires"] == ["30"]


def test_urls_are_signed_for_the_public_address(settings):
    # the browser can't reach the internal address, and the host is part of the signature (D-16)
    settings.MINIO_INTERNAL_URL = "http://minio:9000"
    settings.MINIO_PUBLIC_URL = "http://files.example.com"

    url = urlsplit(storage.presign_put("uploads/abc", "image/png", 5))

    assert url.netloc == "files.example.com"
    assert storage.internal_client().meta.endpoint_url == "http://minio:9000"


# --- calls to the real MinIO (needs-minio in CI) ---


@pytest.fixture
def prefix():
    """A folder of its own for each test, emptied afterwards."""
    prefix = f"tests/{uuid.uuid4()}/"
    yield prefix
    client = storage.internal_client()
    listed = client.list_objects_v2(Bucket=settings.MINIO_BUCKET, Prefix=prefix)
    storage.delete(*(key for item in listed.get("Contents", []) if (key := item.get("Key"))))


def put(key: str, data: bytes, content_type: str = "application/pdf") -> None:
    storage.internal_client().put_object(
        Bucket=settings.MINIO_BUCKET, Key=key, Body=data, ContentType=content_type
    )


def test_head_gives_size_and_type(prefix):
    put(f"{prefix}a", b"hello", "image/png")

    assert storage.head(f"{prefix}a") == storage.ObjectInfo(size=5, content_type="image/png")


def test_head_of_a_missing_object_is_none(prefix):
    assert storage.head(f"{prefix}missing") is None


def test_read_start_gives_the_first_bytes(prefix):
    put(f"{prefix}a", b"0123456789")

    assert storage.read_start(f"{prefix}a", 4) == b"0123"


def test_read_start_of_a_short_object_gives_all_of_it(prefix):
    put(f"{prefix}a", b"hello")

    assert storage.read_start(f"{prefix}a") == b"hello"


def test_read_all(prefix):
    data = bytes(range(256)) * 100
    put(f"{prefix}a", data)

    assert storage.read_all(f"{prefix}a") == data


def test_copy_keeps_the_bytes_and_the_type(prefix):
    put(f"{prefix}from", b"hello", "image/png")

    storage.copy(f"{prefix}from", f"{prefix}to")

    assert storage.read_all(f"{prefix}to") == b"hello"
    assert storage.head(f"{prefix}to") == storage.ObjectInfo(size=5, content_type="image/png")
    assert storage.head(f"{prefix}from") is not None  # the source stays


def test_delete_removes_every_key(prefix):
    put(f"{prefix}a", b"a")
    put(f"{prefix}b", b"b")

    storage.delete(f"{prefix}a", f"{prefix}b")

    assert storage.head(f"{prefix}a") is None
    assert storage.head(f"{prefix}b") is None


def test_delete_of_a_missing_key_is_fine(prefix):
    storage.delete(f"{prefix}missing")


def test_delete_without_keys_does_nothing():
    storage.delete()
