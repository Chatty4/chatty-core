"""GET /files/{file_id}: a 302 to a presigned GET URL for an avatar or a team icon (D-16)."""

import uuid
from urllib.parse import parse_qs, urlsplit

import pytest
from django.conf import settings
from django.utils import timezone

from files.models import File
from shared import storage
from teams.models import Team
from tests.helpers import get_download, headers_for, image_bytes, make_file, make_user

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.usefixtures("remove_objects")]

PNG = image_bytes("PNG")


async def download(client, file_id, headers: dict):
    return await client.get(f"/api/core/v1/files/{file_id}", headers=headers)


async def assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


# --- the redirect ---


async def test_avatar_redirects_to_a_signed_url(async_client, user, auth):
    file = await make_file(user, data=PNG)

    response = await download(async_client, file.id, auth)

    assert response.status_code == 302
    assert response.content == b""
    location = urlsplit(response["Location"])
    query = parse_qs(location.query)
    assert location.netloc == urlsplit(settings.MINIO_PUBLIC_URL).netloc  # D-16
    assert location.path == f"/{settings.MINIO_BUCKET}/{file.object_key}"
    assert query["X-Amz-Expires"] == [str(storage.DOWNLOAD_URL_SECONDS)]
    assert query["response-content-type"] == ["image/png"]
    assert query["response-content-disposition"] == ["inline"]


async def test_the_url_gives_the_image(async_client, user, auth):
    file = await make_file(user, data=PNG)
    response = await download(async_client, file.id, auth)

    status, headers, body = get_download(response["Location"])

    assert status == 200
    assert body == PNG
    assert headers["Content-Type"] == "image/png"
    assert headers["Content-Disposition"] == "inline"


# --- who ---


async def test_any_user_can_download_an_avatar(async_client, user):
    file = await make_file(user)
    other = await headers_for(await make_user("bob@example.com"))

    response = await download(async_client, file.id, other)

    assert response.status_code == 302


async def test_without_token(async_client, user):
    file = await make_file(user)

    response = await download(async_client, file.id, {})

    assert response.status_code == 401


async def test_team_icon_for_a_member(async_client, user, auth, team):
    file = await make_file(user, "team_icon", team)

    response = await download(async_client, file.id, auth)

    assert response.status_code == 302


async def test_team_icon_for_someone_outside_the_team(async_client, user, team):
    file = await make_file(user, "team_icon", team)
    outsider = await headers_for(await make_user("bob@example.com"))

    response = await download(async_client, file.id, outsider)

    await assert_error(response, 403, "not_a_team_member")


async def test_team_icon_of_a_deleted_team(async_client, user, auth, team):
    file = await make_file(user, "team_icon", team)
    await Team.objects.filter(id=team.id).aupdate(deleted_at=timezone.now())

    response = await download(async_client, file.id, auth)

    await assert_error(response, 404, "team_not_found")


# --- which files ---


async def test_attachment_goes_through_chatty_chat(async_client, user, auth, team):
    file = await make_file(user, "attachment", team)

    response = await download(async_client, file.id, auth)

    await assert_error(response, 400, "use_chatty_chat")


@pytest.mark.parametrize(
    "changes",
    [{"status": File.Status.PENDING}, {"deleted_at": timezone.now()}],
    ids=["pending", "deleted"],
)
async def test_unusable_file_looks_missing(async_client, user, auth, changes):
    file = await make_file(user, **changes)

    response = await download(async_client, file.id, auth)

    await assert_error(response, 404, "file_not_found")


async def test_unknown_file(async_client, auth):
    response = await download(async_client, uuid.uuid4(), auth)

    await assert_error(response, 404, "file_not_found")
