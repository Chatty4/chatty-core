from urllib.parse import parse_qs, urlsplit

import pytest
from django.utils import timezone

from files.models import File
from files.services import MAX_ATTACHMENT_SIZE, MAX_IMAGE_SIZE
from teams.models import Team, TeamMember
from tests.helpers import make_user, post_file

pytestmark = pytest.mark.django_db(transaction=True)


# --- status and shape ---


async def test_avatar_returns_201_with_an_upload_url(async_client, user, auth):
    response = await post_file(async_client, auth)

    assert response.status_code == 201
    body = response.json()
    assert body == {
        "file_id": body["file_id"],
        "upload_url": body["upload_url"],
        "upload_method": "PUT",
        "upload_headers": {"Content-Type": "image/png", "Content-Length": "5"},
        "expires_at": body["expires_at"],
    }


async def test_url_is_signed_for_the_temporary_key(async_client, auth):
    body = (await post_file(async_client, auth)).json()

    url = urlsplit(body["upload_url"])
    query = parse_qs(url.query)
    # the public address (D-16) and uploads/, never the final key (D-15)
    assert url.netloc == "127.0.0.1:9000"
    assert url.path == f"/chatty/uploads/{body['file_id']}"
    assert query["X-Amz-SignedHeaders"] == ["content-length;content-type;host"]
    assert query["X-Amz-Expires"] == ["600"]


async def test_avatar_row_is_pending(async_client, user, auth):
    before = timezone.now()
    body = (await post_file(async_client, auth)).json()

    file = await File.objects.aget(id=body["file_id"])
    assert file.owner_id == user.id
    assert file.team_id is None
    assert file.purpose == File.Purpose.AVATAR
    assert file.status == File.Status.PENDING
    assert file.object_key == f"avatars/{user.id}/{file.id}"
    assert (file.filename, file.mime, file.size) == ("me.png", "image/png", 5)
    assert file.attached_at is None and file.deleted_at is None
    expected = before.timestamp() + 600
    assert expected <= file.upload_expires_at.timestamp() <= expected + 5


@pytest.mark.parametrize(
    ("purpose", "mime", "prefix"),
    [
        ("team_icon", "image/webp", "team-icons"),
        ("attachment", "application/pdf", "attachments"),
    ],
)
async def test_team_files_get_a_team_key(async_client, auth, team, purpose, mime, prefix):
    response = await post_file(async_client, auth, purpose=purpose, team_id=str(team.id), mime=mime)

    assert response.status_code == 201
    file = await File.objects.aget(id=response.json()["file_id"])
    assert file.team_id == team.id
    assert file.object_key == f"{prefix}/{team.id}/{file.id}"


async def test_attachment_accepts_any_type(async_client, auth, team):
    response = await post_file(
        async_client, auth, purpose="attachment", team_id=str(team.id), mime="application/x-what"
    )

    assert response.status_code == 201


@pytest.mark.parametrize(
    ("purpose", "size"), [("avatar", MAX_IMAGE_SIZE), ("attachment", MAX_ATTACHMENT_SIZE)]
)
async def test_size_limit_itself_is_allowed(async_client, auth, team, purpose, size):
    team_id = str(team.id) if purpose == "attachment" else None
    response = await post_file(async_client, auth, purpose=purpose, team_id=team_id, size=size)

    assert response.status_code == 201


# --- filename ---


@pytest.mark.parametrize(
    ("sent", "saved"),
    [
        ("../../evil\\name.png", "....evilname.png"),
        ("  photo.png  ", "photo.png"),
        ("invoice‮fdp.exe", "invoicefdp.exe"),
        ("tab\tand\nnewline.png", "tabandnewline.png"),
        ("raport final.pdf", "raport final.pdf"),
    ],
)
async def test_filename_is_cleaned(async_client, auth, sent, saved):
    response = await post_file(async_client, auth, filename=sent)

    assert response.status_code == 201
    file = await File.objects.aget(id=response.json()["file_id"])
    assert file.filename == saved


# --- validation errors ---


@pytest.mark.parametrize(
    ("changes", "fields"),
    [
        ({"purpose": "video"}, {"purpose": "invalid_choice"}),
        ({"team_id": "00000000-0000-0000-0000-000000000001"}, {"team_id": "invalid"}),
        ({"purpose": "attachment"}, {"team_id": "required"}),
        ({"purpose": "team_icon"}, {"team_id": "required"}),
        ({"purpose": "attachment", "team_id": "not-a-uuid"}, {"team_id": "invalid"}),
        ({"filename": ""}, {"filename": "blank"}),
        ({"filename": "a" * 256}, {"filename": "too_long"}),
        ({"filename": "/\\\x07"}, {"filename": "invalid"}),
        # DRF refuses NUL before the cleaning runs; Postgres can't store it in text anyway
        ({"filename": "a\x00.png"}, {"filename": "null_characters_not_allowed"}),
        ({"size": 0}, {"size": "min_value"}),
        ({"size": "abc"}, {"size": "invalid"}),
        ({"mime": None}, {"mime": "required"}),
        ({"mime": "x" * 256}, {"mime": "too_long"}),
    ],
)
async def test_bad_body_is_a_validation_error(async_client, auth, changes, fields):
    response = await post_file(async_client, auth, **changes)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["fields"] == fields
    assert await File.objects.acount() == 0


# --- rules ---


@pytest.mark.parametrize("mime", ["image/svg+xml", "application/pdf", "image/bmp"])
async def test_image_purposes_take_only_four_types(async_client, auth, mime):
    response = await post_file(async_client, auth, mime=mime)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "type_not_allowed"
    assert await File.objects.acount() == 0


@pytest.mark.parametrize(
    ("purpose", "size"), [("avatar", MAX_IMAGE_SIZE + 1), ("attachment", MAX_ATTACHMENT_SIZE + 1)]
)
async def test_over_the_size_limit(async_client, auth, team, purpose, size):
    team_id = str(team.id) if purpose == "attachment" else None
    response = await post_file(async_client, auth, purpose=purpose, team_id=team_id, size=size)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "file_too_large"
    assert await File.objects.acount() == 0


async def test_team_file_for_a_team_im_not_in(async_client, auth):
    other = await make_user("bob@example.com")
    team = await Team.objects.acreate(name="Theirs", created_by=other)
    await TeamMember.objects.acreate(team=team, user=other, role=TeamMember.Role.OWNER)

    response = await post_file(async_client, auth, purpose="attachment", team_id=str(team.id))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_a_team_member"
    assert await File.objects.acount() == 0


async def test_team_file_for_a_deleted_team(async_client, auth, team):
    await Team.objects.filter(id=team.id).aupdate(deleted_at=timezone.now())

    response = await post_file(async_client, auth, purpose="team_icon", team_id=str(team.id))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "team_not_found"
    assert await File.objects.acount() == 0


async def test_needs_a_token(async_client):
    response = await post_file(async_client, {})

    assert response.status_code == 401
    assert await File.objects.acount() == 0


async def test_upload_url_is_never_logged(async_client, auth, caplog):
    caplog.set_level("DEBUG")

    body = (await post_file(async_client, auth)).json()

    assert body["upload_url"] not in caplog.text
    assert "X-Amz-Signature" not in caplog.text
