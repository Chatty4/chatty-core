import hashlib

import pytest
from asgiref.sync import sync_to_async

from authn.models import RefreshToken
from shared.redis import get_redis_client
from users.models import User

pytestmark = pytest.mark.django_db(transaction=True)

LOGIN_URL = "/api/core/v1/auth/login"
LOGOUT_URL = "/api/core/v1/auth/logout"
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


async def test_logout_deletes_refresh_token(async_client, tokens):
    access = tokens["access_token"]
    refresh = tokens["refresh_token"]

    response = await async_client.post(
        LOGOUT_URL,
        {"refresh_token": refresh},
        content_type="application/json",
        headers={"Authorization": f"Bearer {access}"},
    )

    assert response.status_code == 204
    token_hash = hashlib.sha256(refresh.encode()).hexdigest()
    assert not await RefreshToken.objects.filter(token_hash=token_hash).aexists()


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


async def test_logout_other_users_rotated_token_returns_403(async_client, tokens):
    """User B cannot use another user's already-rotated token to get a silent 204."""
    user_b = await sync_to_async(User.objects.create_user)(
        email="bob2@example.com", display_name="Bob", password=PASSWORD
    )
    b_resp = await async_client.post(
        LOGIN_URL,
        {"email": "bob2@example.com", "password": PASSWORD},
        content_type="application/json",
    )
    b_tokens = b_resp.json()

    # Rotate A's token first, so the old row still exists
    await async_client.post(
        REFRESH_URL,
        {"refresh_token": tokens["refresh_token"]},
        content_type="application/json",
    )

    # B tries to logout with A's now-rotated token → must be 403, not 204
    response = await async_client.post(
        LOGOUT_URL,
        {"refresh_token": tokens["refresh_token"]},
        content_type="application/json",
        headers={"Authorization": f"Bearer {b_tokens['access_token']}"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"

    await sync_to_async(user_b.delete)()


async def test_logout_other_users_token_returns_403(async_client, tokens):
    """User B cannot revoke user A's refresh token; A's token must remain active."""
    # tokens belongs to user A (the `user` fixture); create user B and log them in
    user_b = await sync_to_async(User.objects.create_user)(
        email="bob@example.com", display_name="Bob", password=PASSWORD
    )
    b_response = await async_client.post(
        LOGIN_URL,
        {"email": "bob@example.com", "password": PASSWORD},
        content_type="application/json",
    )
    b_tokens = b_response.json()

    response = await async_client.post(
        LOGOUT_URL,
        {"refresh_token": tokens["refresh_token"]},  # A's token
        content_type="application/json",
        headers={"Authorization": f"Bearer {b_tokens['access_token']}"},  # B's access
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"

    # A's token must still be valid — refresh should succeed
    refresh_response = await async_client.post(
        "/api/core/v1/auth/refresh",
        {"refresh_token": tokens["refresh_token"]},
        content_type="application/json",
    )
    assert refresh_response.status_code == 200

    await sync_to_async(user_b.delete)()
