import hashlib

import pytest
from asgiref.sync import sync_to_async

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


async def change(client, tokens, old=OLD, new=NEW):
    body = {"old_password": old, "new_password": new, "refresh_token": tokens.refresh_token}
    headers = {"Authorization": f"Bearer {tokens.access_token}"}
    return await client.post(URL, body, content_type="application/json", headers=headers)


async def is_revoked(raw: str) -> bool:
    token = await RefreshToken.objects.aget(token_hash=hashlib.sha256(raw.encode()).hexdigest())
    return token.revoked_at is not None


async def test_change_password(async_client, user, this_device, other_device):
    response = await change(async_client, this_device)

    assert response.status_code == 204
    saved = await User.objects.aget(id=user.id)
    assert await sync_to_async(saved.check_password)(NEW)
    assert not await is_revoked(this_device.refresh_token)
    assert await is_revoked(other_device.refresh_token)


async def test_wrong_old_password(async_client, user, this_device, other_device):
    response = await change(async_client, this_device, old="not my password")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "wrong_password"
    assert not await is_revoked(other_device.refresh_token)


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
