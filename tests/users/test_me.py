import pytest
from asgiref.sync import sync_to_async

from authn.services import AuthnService
from users.models import User

pytestmark = pytest.mark.django_db(transaction=True)

URL = "/api/core/v1/me"
BODY = {"display_name": "Ana P.", "timezone": "Europe/Bucharest", "avatar_file_id": None}


@pytest.fixture
async def user():
    return await sync_to_async(User.objects.create_user)(
        email="ana@example.com", display_name="Ana Pop", password="correct horse battery"
    )


@pytest.fixture
async def auth(user):
    tokens = await AuthnService().issue_tokens(user)
    return {"Authorization": f"Bearer {tokens.access_token}"}


async def put_me(client, body, headers):
    return await client.put(URL, body, content_type="application/json", headers=headers)


async def test_get_me(async_client, auth):
    response = await async_client.get(URL, headers=auth)

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "ana@example.com"
    assert body["display_name"] == "Ana Pop"
    assert body["timezone"] == "UTC"
    assert body["avatar_file_id"] is None
    assert body["date_joined"]
    assert body["teams"] == []


async def test_get_me_without_token(async_client):
    response = await async_client.get(URL)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_get_me_bad_token(async_client):
    response = await async_client.get(URL, headers={"Authorization": "Bearer nope"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_get_me_inactive_user(async_client, user, auth):
    user.is_active = False
    await user.asave(update_fields=["is_active"])

    response = await async_client.get(URL, headers=auth)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "user_inactive"


async def test_put_me(async_client, user, auth):
    response = await put_me(async_client, BODY, auth)

    assert response.status_code == 200
    assert response.json()["display_name"] == "Ana P."
    assert response.json()["timezone"] == "Europe/Bucharest"
    saved = await User.objects.aget(id=user.id)
    assert saved.display_name == "Ana P."
    assert saved.timezone == "Europe/Bucharest"


async def test_put_me_without_token(async_client):
    response = await put_me(async_client, BODY, {})

    assert response.status_code == 401


async def test_put_me_invalid_fields(async_client, auth):
    body = {"display_name": "", "timezone": "Mars/Base"}
    response = await put_me(async_client, body, auth)

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {
        "display_name": "blank",
        "timezone": "invalid",
        "avatar_file_id": "required",
    }
