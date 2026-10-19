import hashlib
from datetime import timedelta

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from authn.models import RefreshToken
from authn.services import AuthnService
from shared.redis import get_redis_client
from users.models import User

pytestmark = pytest.mark.django_db(transaction=True)

URL = "/api/core/v1/auth/password"


@pytest.fixture(autouse=True)
async def redis_cleanup():
    get_redis_client.cache_clear()
    yield
    await get_redis_client().aclose()
    get_redis_client.cache_clear()


OLD = "correct horse battery"
NEW = "a much longer passphrase"


@pytest.fixture
async def user():
    return await sync_to_async(User.objects.create_user)(
        email="ana@example.com", display_name="Ana Pop", password=OLD
    )


@pytest.fixture
async def this_device(user):
    return await AuthnService().issue_tokens(user)


@pytest.fixture
async def other_device(user):
    return await AuthnService().issue_tokens(user)


@pytest.fixture
async def stranger():
    stranger = await sync_to_async(User.objects.create_user)(
        email="bob@example.com", display_name="Bob", password=OLD
    )
    return await AuthnService().issue_tokens(stranger)


async def password_is_old(user) -> bool:
    saved = await User.objects.aget(id=user.id)
    return await sync_to_async(saved.check_password)(OLD)


async def change(client, tokens, old=OLD, new=NEW):
    body = {"old_password": old, "new_password": new, "refresh_token": tokens.refresh_token}
    headers = {"Authorization": f"Bearer {tokens.access_token}"}
    return await client.post(URL, body, content_type="application/json", headers=headers)


async def is_logged_out(raw: str) -> bool:
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    return not await RefreshToken.objects.filter(token_hash=token_hash).aexists()


async def test_change_password(async_client, user, this_device, other_device):
    response = await change(async_client, this_device)

    assert response.status_code == 204
    saved = await User.objects.aget(id=user.id)
    assert await sync_to_async(saved.check_password)(NEW)
    assert not await is_logged_out(this_device.refresh_token)
    assert await is_logged_out(other_device.refresh_token)


async def test_wrong_old_password(async_client, user, this_device, other_device):
    response = await change(async_client, this_device, old="not my password")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "wrong_password"
    assert not await is_logged_out(other_device.refresh_token)


async def test_same_password(async_client, this_device):
    response = await change(async_client, this_device, new=OLD)

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {"new_password": "invalid"}


async def test_weak_new_password(async_client, this_device):
    response = await change(async_client, this_device, new="123")

    assert response.status_code == 400
    assert "new_password" in response.json()["error"]["fields"]


async def test_without_token(async_client):
    response = await async_client.post(URL, {}, content_type="application/json")

    assert response.status_code == 401


async def test_wrong_old_password_rate_limited_after_5_failures(async_client, user, this_device):
    for _ in range(5):
        await change(async_client, this_device, old="wrong password")

    response = await change(async_client, this_device, old="wrong password")

    assert response.status_code == 429


async def test_unknown_refresh_token(async_client, user, this_device, other_device):
    this_device.refresh_token = "rt_garbage"

    response = await change(async_client, this_device)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_refresh_token"
    assert await password_is_old(user)
    assert not await is_logged_out(other_device.refresh_token)


async def test_other_users_refresh_token(async_client, user, this_device, other_device, stranger):
    this_device.refresh_token = stranger.refresh_token

    response = await change(async_client, this_device)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
    assert await password_is_old(user)
    assert not await is_logged_out(other_device.refresh_token)
    assert not await is_logged_out(stranger.refresh_token)


async def test_revoked_refresh_token(async_client, user, this_device, other_device):
    await AuthnService().revoke_refresh_token(this_device.refresh_token, str(user.id))

    response = await change(async_client, this_device)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_refresh_token"
    assert await password_is_old(user)
    assert not await is_logged_out(other_device.refresh_token)


async def test_expired_refresh_token(async_client, user, this_device, other_device):
    await RefreshToken.objects.filter(user=user).aupdate(
        expires_at=timezone.now() - timedelta(minutes=1)
    )

    response = await change(async_client, this_device)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_refresh_token"
    assert await password_is_old(user)


async def test_failed_save_keeps_other_sessions(
    async_client, user, this_device, other_device, monkeypatch
):
    def boom(*args):
        raise RuntimeError("db down")

    monkeypatch.setattr("users.repositories.UserRepository.set_password_sync", boom)

    response = await change(async_client, this_device)

    assert response.status_code == 500
    assert await password_is_old(user)
    assert not await is_logged_out(other_device.refresh_token)


async def test_bad_refresh_token_with_right_password_is_not_a_failed_attempt(
    async_client, user, this_device
):
    good = this_device.refresh_token
    this_device.refresh_token = "rt_garbage"
    for _ in range(5):
        await change(async_client, this_device)

    this_device.refresh_token = good
    response = await change(async_client, this_device)

    assert response.status_code == 204
