import pytest

pytestmark = pytest.mark.urls("tests.shared.urls")


async def test_async_handler_returns_its_response(async_client):
    response = await async_client.get("/ok")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


async def test_domain_error_raised_in_a_handler(async_client):
    response = await async_client.get("/missing")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "team_not_found"


async def test_error_raised_before_the_handler(async_client):
    # The permission check runs in initial(), in a thread.
    response = await async_client.get("/forbidden")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


async def test_unsupported_method(async_client):
    response = await async_client.post("/ok")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


async def test_unhandled_error_does_not_leak_details(async_client):
    response = await async_client.get("/crash")

    assert response.status_code == 500
    assert "secret detail" not in response.content.decode()
    assert response.json()["error"]["code"] == "internal_error"
