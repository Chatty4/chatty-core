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
