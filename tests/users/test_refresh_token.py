import pytest
from asgiref.sync import sync_to_async

from authn.models import RefreshToken
from shared.redis import get_redis_client
from users.models import User

pytestmark = pytest.mark.django_db(transaction=True)

LOGIN_URL = "/api/core/v1/auth/login"
REFRESH_URL = "/api/core/v1/auth/refresh"
EMAIL = "ana@example.com"
PASSWORD = "correct horse battery"


@pytest.fixture(autouse=True)
async def redis_cleanup():
    get_redis_client.cache_clear()
    yield
    await get_redis_client().aclose()
    get_redis_client.cache_clear()


@pytest.fixture
async def user():
    return await sync_to_async(User.objects.create_user)(
        email=EMAIL, display_name="Ana Pop", password=PASSWORD
    )


@pytest.fixture
async def tokens(async_client, user):
    response = await async_client.post(
        LOGIN_URL,
        {"email": EMAIL, "password": PASSWORD},
        content_type="application/json",
    )
    return response.json()


async def test_refresh_returns_new_token_pair(async_client, tokens):
    response = await async_client.post(
        REFRESH_URL,
        {"refresh_token": tokens["refresh_token"]},
        content_type="application/json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "Bearer"
    assert body["access_token"]
    assert body["refresh_token"].startswith("rt_")
    assert body["refresh_token"] != tokens["refresh_token"]
    assert body["expires_in"] == 900
    assert body["refresh_expires_in"] == 2592000


async def test_refresh_revokes_old_token(async_client, tokens):
    old_refresh = tokens["refresh_token"]

    await async_client.post(
        REFRESH_URL,
        {"refresh_token": old_refresh},
        content_type="application/json",
    )

    import hashlib

    old_hash = hashlib.sha256(old_refresh.encode()).hexdigest()
    token = await RefreshToken.objects.filter(token_hash=old_hash).afirst()
    assert token is not None
    assert token.revoked_at is not None


async def test_refresh_old_token_is_rejected(async_client, tokens):
    old_refresh = tokens["refresh_token"]

    await async_client.post(
        REFRESH_URL,
        {"refresh_token": old_refresh},
        content_type="application/json",
    )
    response = await async_client.post(
        REFRESH_URL,
        {"refresh_token": old_refresh},
        content_type="application/json",
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_refresh_token"


async def test_refresh_unknown_token_is_rejected(async_client, user):
    response = await async_client.post(
        REFRESH_URL,
        {"refresh_token": "rt_" + "a" * 64},
        content_type="application/json",
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_refresh_token"


async def test_refresh_inactive_user_is_rejected(async_client, tokens, user):
    user.is_active = False
    await user.asave(update_fields=["is_active"])

    response = await async_client.post(
        REFRESH_URL,
        {"refresh_token": tokens["refresh_token"]},
        content_type="application/json",
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "user_inactive"


async def test_refresh_missing_field(async_client, user):
    response = await async_client.post(
        REFRESH_URL,
        {},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {"refresh_token": "required"}
