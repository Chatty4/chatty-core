import pytest
from django.core.cache import cache

from users.models import User

# transaction=True: the view writes through sync_to_async on another DB connection, so the
# per-test rollback would miss those rows; this truncates the tables after each test instead.
pytestmark = pytest.mark.django_db(transaction=True)

URL = "/api/core/v1/auth/register"
VALID = {"email": "ana@example.com", "display_name": "Ana Pop", "password": "correct horse battery"}


@pytest.fixture(autouse=True)
def clear_throttle():
    # the throttle counts in the cache, which lives for the whole test run
    cache.clear()


async def register(client, body):
    return await client.post(URL, body, content_type="application/json")


async def test_register_creates_user(async_client):
    response = await register(async_client, VALID)

    assert response.status_code == 201
    body = response.json()
    assert body == {
        "id": body["id"],
        "email": "ana@example.com",
        "display_name": "Ana Pop",
        "avatar_file_id": None,
        "timezone": "UTC",
    }
    user = await User.objects.aget(id=body["id"])
    assert user.password != VALID["password"]
    assert user.check_password(VALID["password"])


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("email", "not-an-email", "invalid"),
        ("display_name", "", "blank"),
        ("display_name", "a" * 61, "too_long"),
        ("password", "xq7!mz2pk", "password_too_short"),
        ("password", "1234567890", "password_too_common"),
        ("password", "8402957163", "password_entirely_numeric"),
        ("password", "anapopescu1", "password_too_similar"),
    ],
)
async def test_register_invalid_field(async_client, field, value, reason):
    body = {**VALID, "email": "anapopescu@example.com", field: value}

    response = await register(async_client, body)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["fields"] == {field: reason}


async def test_register_missing_fields(async_client):
    response = await register(async_client, {})

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {
        "email": "required",
        "display_name": "required",
        "password": "required",
    }


async def test_register_email_taken(async_client):
    await register(async_client, VALID)

    response = await register(async_client, VALID)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_taken"


@pytest.mark.skip(reason="rate limit comes with the Redis rate limiter (CHAT-237)")
async def test_register_rate_limited_after_10_per_hour(async_client):
    # the throttle runs before validation, so empty bodies count too and skip password hashing
    for _ in range(10):
        assert (await register(async_client, {})).status_code == 400

    response = await register(async_client, {})

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"
    assert int(response["Retry-After"]) > 0
