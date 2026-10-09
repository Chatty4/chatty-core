import pytest

pytestmark = pytest.mark.urls("tests.shared.urls")

TOKEN = "test-service-token"


@pytest.fixture(autouse=True)
def service_token(settings):
    settings.CORE_SERVICE_TOKEN = TOKEN


async def test_right_token(async_client):
    response = await async_client.get("/internal", headers={"X-Service-Token": TOKEN})

    assert response.status_code == 200
    assert response.json() == {"ok": True}


@pytest.mark.parametrize("headers", [{}, {"X-Service-Token": ""}, {"X-Service-Token": "wrong"}])
async def test_missing_or_wrong_token(async_client, headers):
    response = await async_client.get("/internal", headers=headers)

    assert response.status_code == 401
    assert response.json() == {
        "error": {"code": "invalid_service_token", "message": "missing or wrong X-Service-Token"}
    }


async def test_empty_configured_token_rejects_missing_header(async_client, settings):
    settings.CORE_SERVICE_TOKEN = ""

    response = await async_client.get("/internal")

    assert response.status_code == 401
