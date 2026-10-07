import pytest
from django.db import OperationalError

pytestmark = pytest.mark.django_db


async def test_health_ok(async_client):
    response = await async_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok"}


async def test_health_db_down(async_client, monkeypatch):
    def broken_ping():
        raise OperationalError("database is down")

    monkeypatch.setattr("config.views.ping_db", broken_ping)

    response = await async_client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "db": "error"}


async def test_health_only_allows_get(async_client):
    response = await async_client.post("/health")

    assert response.status_code == 405
