import pytest
from django.db import OperationalError
from redis.exceptions import ConnectionError as RedisConnectionError

from shared.redis import get_redis_client

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
async def redis_client():
    # each test has its own event loop, so the cached client must not outlive the test
    get_redis_client.cache_clear()
    yield
    await get_redis_client().aclose()
    get_redis_client.cache_clear()


async def test_health_ok(async_client):
    response = await async_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok", "redis": "ok"}


async def test_health_db_down(async_client, monkeypatch):
    def broken_ping():
        raise OperationalError("database is down")

    monkeypatch.setattr("config.views.ping_db", broken_ping)

    response = await async_client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "db": "error", "redis": "ok"}


async def test_health_redis_down(async_client, monkeypatch):
    async def broken_ping():
        raise RedisConnectionError("redis is down")

    monkeypatch.setattr("config.views.ping_redis", broken_ping)

    response = await async_client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "db": "ok", "redis": "error"}


async def test_health_only_allows_get(async_client):
    response = await async_client.post("/health")

    assert response.status_code == 405
