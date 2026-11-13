from datetime import timedelta

import pytest
from django.utils import timezone

from files.models import File
from files.services import MAX_PENDING_UPLOADS, UPLOAD_LIMIT
from tests.helpers import headers_for, make_user, post_file

pytestmark = pytest.mark.django_db(transaction=True)


async def fill_pending(client, auth, count: int = MAX_PENDING_UPLOADS) -> None:
    for _ in range(count):
        assert (await post_file(client, auth)).status_code == 201


# --- open uploads (pending, not expired, not deleted) ---


async def test_cap_of_open_uploads(async_client, auth):
    await fill_pending(async_client, auth)

    response = await post_file(async_client, auth)

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"
    # the oldest open upload expires in about 10 minutes and frees a slot
    assert 590 <= int(response["Retry-After"]) <= 600
    assert await File.objects.acount() == MAX_PENDING_UPLOADS


async def test_expired_upload_frees_a_slot(async_client, auth):
    await fill_pending(async_client, auth)
    oldest = await File.objects.order_by("created_at").afirst()
    await File.objects.filter(id=oldest.id).aupdate(
        upload_expires_at=timezone.now() - timedelta(seconds=1)
    )

    response = await post_file(async_client, auth)

    assert response.status_code == 201


async def test_retry_after_comes_from_the_oldest_open_upload(async_client, auth):
    await fill_pending(async_client, auth)
    oldest = await File.objects.order_by("created_at").afirst()
    await File.objects.filter(id=oldest.id).aupdate(
        upload_expires_at=timezone.now() + timedelta(seconds=30)
    )

    response = await post_file(async_client, auth)

    assert response.status_code == 429
    assert 25 <= int(response["Retry-After"]) <= 30


async def test_confirmed_upload_doesnt_count(async_client, auth):
    await fill_pending(async_client, auth)
    oldest = await File.objects.order_by("created_at").afirst()
    await File.objects.filter(id=oldest.id).aupdate(status=File.Status.READY)

    response = await post_file(async_client, auth)

    assert response.status_code == 201


async def test_deleted_upload_doesnt_count(async_client, auth):
    await fill_pending(async_client, auth)
    oldest = await File.objects.order_by("created_at").afirst()
    await File.objects.filter(id=oldest.id).aupdate(deleted_at=timezone.now())

    response = await post_file(async_client, auth)

    assert response.status_code == 201


async def test_cap_is_per_user(async_client, auth):
    await fill_pending(async_client, auth)
    other = await make_user("bob@example.com")

    response = await post_file(async_client, await headers_for(other))

    assert response.status_code == 201


# --- rate limit: requests per minute ---


async def test_rate_limited_after_30_per_minute(async_client, auth, monkeypatch):
    # raise the cap of open uploads, so only the per-minute limit applies
    monkeypatch.setattr("files.services.MAX_PENDING_UPLOADS", UPLOAD_LIMIT + 10)
    await fill_pending(async_client, auth, UPLOAD_LIMIT)

    response = await post_file(async_client, auth)

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"
    assert 1 <= int(response["Retry-After"]) <= 60
    assert await File.objects.acount() == UPLOAD_LIMIT


async def test_bad_requests_dont_count_against_the_rate_limit(async_client, auth, monkeypatch):
    monkeypatch.setattr("files.services.MAX_PENDING_UPLOADS", UPLOAD_LIMIT + 10)
    for _ in range(UPLOAD_LIMIT):
        assert (await post_file(async_client, auth, purpose="video")).status_code == 400

    response = await post_file(async_client, auth)

    assert response.status_code == 201
