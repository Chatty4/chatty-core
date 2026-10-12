import pytest
from asgiref.sync import sync_to_async

from authn.models import RefreshToken
from shared.redis import get_redis_client
from users.models import User

pytestmark = pytest.mark.django_db(transaction=True)

LOGIN_URL = "/api/core/v1/auth/login"
LOGOUT_URL = "/api/core/v1/auth/logout"
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


async def test_logout_revokes_refresh_token(async_client, tokens):
    access = tokens["access_token"]
    refresh = tokens["refresh_token"]

    response = await async_client.post(
        LOGOUT_URL,
        {"refresh_token": refresh},
        content_type="application/json",
        headers={"Authorization": f"Bearer {access}"},
    )

    assert response.status_code == 204
    token = await RefreshToken.objects.filter(token_hash__isnull=False).afirst()
    assert token is not None
    assert token.revoked_at is not None


async def test_logout_unknown_token_is_no_op(async_client, tokens):
    response = await async_client.post(
        LOGOUT_URL,
        {"refresh_token": "rt_" + "a" * 64},
        content_type="application/json",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )

    assert response.status_code == 204


async def test_logout_already_revoked_is_no_op(async_client, tokens):
    access = tokens["access_token"]
    refresh = tokens["refresh_token"]

    await async_client.post(
        LOGOUT_URL,
        {"refresh_token": refresh},
        content_type="application/json",
        headers={"Authorization": f"Bearer {access}"},
    )
    response = await async_client.post(
        LOGOUT_URL,
        {"refresh_token": refresh},
        content_type="application/json",
        headers={"Authorization": f"Bearer {access}"},
    )

    assert response.status_code == 204


async def test_logout_requires_authentication(async_client, tokens):
    response = await async_client.post(
        LOGOUT_URL,
        {"refresh_token": tokens["refresh_token"]},
        content_type="application/json",
    )

    assert response.status_code == 401


async def test_logout_missing_refresh_token_field(async_client, tokens):
    response = await async_client.post(
        LOGOUT_URL,
        {},
        content_type="application/json",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {"refresh_token": "required"}
