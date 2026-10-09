import pytest
from asgiref.sync import sync_to_async

from shared.redis import clear_rate_limit, get_redis_client
from users.models import User

pytestmark = pytest.mark.django_db(transaction=True)

URL = "/api/core/v1/auth/login"
EMAIL = "ana@example.com"
PASSWORD = "correct horse battery"
RATE_KEY_IP = "login_fail:127.0.0.1"
RATE_KEY_EMAIL = f"login_fail:{EMAIL}"


@pytest.fixture
async def user():
    return await sync_to_async(User.objects.create_user)(
        email=EMAIL, display_name="Ana Pop", password=PASSWORD
    )


@pytest.fixture(autouse=True)
async def redis_client():
    get_redis_client.cache_clear()
    for key in (RATE_KEY_IP, RATE_KEY_EMAIL):
        await clear_rate_limit(key)
    yield
    for key in (RATE_KEY_IP, RATE_KEY_EMAIL):
        await clear_rate_limit(key)
    await get_redis_client().aclose()
    get_redis_client.cache_clear()


async def login(client, body):
    return await client.post(URL, body, content_type="application/json")


async def test_login_returns_token_pair(async_client, user):
    response = await login(async_client, {"email": EMAIL, "password": PASSWORD})

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "Bearer"
    assert body["access_token"]
    assert body["refresh_token"].startswith("rt_")
    assert body["expires_in"] == 900
    assert body["refresh_expires_in"] == 2592000


async def test_login_wrong_password(async_client, user):
    response = await login(async_client, {"email": EMAIL, "password": "wrongpassword"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


async def test_login_unknown_email(async_client):
    response = await login(async_client, {"email": "nobody@example.com", "password": PASSWORD})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


async def test_login_missing_fields(async_client):
    response = await login(async_client, {})

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {"email": "required", "password": "required"}


async def test_login_inactive_user(async_client, user):
    user.is_active = False
    await user.asave(update_fields=["is_active"])

    response = await login(async_client, {"email": EMAIL, "password": PASSWORD})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "user_inactive"


async def test_login_rate_limited_after_5_failures(async_client, user):
    for _ in range(5):
        await login(async_client, {"email": EMAIL, "password": "wrong"})

    response = await login(async_client, {"email": EMAIL, "password": "wrong"})

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"
    assert int(response["Retry-After"]) > 0


async def test_login_success_not_counted_against_limit(async_client, user):
    # successful logins must not consume failure quota
    for _ in range(4):
        await login(async_client, {"email": EMAIL, "password": "wrong"})
    await login(async_client, {"email": EMAIL, "password": PASSWORD})

    # 4 failures + 1 success: still 4 failures recorded, next failure should not be blocked
    response = await login(async_client, {"email": EMAIL, "password": "wrong"})

    assert response.status_code == 401  # not 429
