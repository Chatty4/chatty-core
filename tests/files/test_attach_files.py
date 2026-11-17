"""POST /internal/files/attach: all the files of a message are attached, or none (D-03)."""

import uuid

import pytest
from django.conf import settings
from django.utils import timezone

from files.models import File
from teams.models import Team
from tests.helpers import headers_for, make_file, make_user

pytestmark = pytest.mark.django_db(transaction=True)

SERVICE = {"X-Service-Token": settings.CORE_SERVICE_TOKEN}


async def attach(client, user, channel_id, *files, headers: dict = SERVICE):
    body = {
        "user_id": str(user.id),
        "channel_id": str(channel_id),
        "file_ids": [str(getattr(file, "id", file)) for file in files],
    }
    return await client.post(
        "/internal/files/attach", body, content_type="application/json", headers=headers
    )


async def assert_error(response, status: int, code: str, file_id=None) -> None:
    assert response.status_code == status
    error = response.json()["error"]
    assert error["code"] == code
    if file_id is not None:
        assert error["fields"] == {"file_id": str(file_id)}


async def is_attached(file) -> bool:
    return (await File.objects.aget(id=file.id)).attached_at is not None


# --- attached ---


async def test_attach_two_files(async_client, user, team, channel):
    report = await make_file(
        user, "attachment", team, filename="report.pdf", mime="application/pdf", size=482133
    )
    chart = await make_file(user, "attachment", team, filename="chart.png")

    response = await attach(async_client, user, channel.id, chart, report)

    assert response.status_code == 200
    first, second = response.json()["attachments"]
    assert first["file_id"] == str(chart.id)  # the order of file_ids
    assert second == {
        "file_id": str(report.id),
        "object_key": report.object_key,
        "filename": "report.pdf",
        "mime": "application/pdf",
        "size": 482133,
        "attached_at": second["attached_at"],
    }
    assert second["attached_at"] is not None
    assert await is_attached(chart) and await is_attached(report)


# --- each check, with the file it names ---


async def bad_file(kind: str, user, team):
    """A file that fails exactly one check, or an unknown id."""
    if kind == "unknown":
        return uuid.uuid4()
    if kind == "other_user":
        return await make_file(await make_user("bob@example.com"), "attachment", team)
    if kind == "avatar":
        return await make_file(user)
    if kind == "team_icon":
        return await make_file(user, "team_icon", team)
    if kind == "other_team":
        other = await Team.objects.acreate(name="Design", created_by=user)
        return await make_file(user, "attachment", other)
    changes = {
        "deleted": {"deleted_at": timezone.now()},
        "pending": {"status": File.Status.PENDING},
        "attached": {"attached_at": timezone.now()},
    }[kind]
    return await make_file(user, "attachment", team, **changes)


@pytest.mark.parametrize(
    ("kind", "status", "code"),
    [
        ("unknown", 404, "file_not_found"),
        ("deleted", 404, "file_not_found"),
        ("other_user", 403, "not_file_owner"),
        ("avatar", 400, "wrong_purpose"),
        ("team_icon", 400, "wrong_purpose"),
        ("other_team", 400, "wrong_team"),
        ("pending", 409, "file_not_ready"),
        ("attached", 409, "file_already_attached"),
    ],
)
async def test_each_check_attaches_nothing(async_client, user, team, channel, kind, status, code):
    good = await make_file(user, "attachment", team)
    bad = await bad_file(kind, user, team)

    response = await attach(async_client, user, channel.id, good, bad)

    await assert_error(response, status, code, getattr(bad, "id", bad))
    assert not await is_attached(good)  # all or nothing


async def test_checks_run_in_order(async_client, user, team, channel):
    pending_of_bob = await make_file(
        await make_user("bob@example.com"), "attachment", team, status=File.Status.PENDING
    )

    response = await attach(async_client, user, channel.id, pending_of_bob)

    await assert_error(response, 403, "not_file_owner", pending_of_bob.id)  # check 2 before 5


async def test_the_first_failing_file_is_named(async_client, user, team, channel):
    pending = await make_file(user, "attachment", team, status=File.Status.PENDING)
    avatar = await make_file(user)

    response = await attach(async_client, user, channel.id, pending, avatar)

    await assert_error(response, 409, "file_not_ready", pending.id)


# --- the channel ---


async def test_unknown_channel(async_client, user, team):
    file = await make_file(user, "attachment", team)
    response = await attach(async_client, user, uuid.uuid4(), file)

    await assert_error(response, 404, "channel_not_found")
    assert not await is_attached(file)


async def test_channel_of_a_deleted_team(async_client, user, team, channel):
    file = await make_file(user, "attachment", team)
    await Team.objects.filter(id=team.id).aupdate(deleted_at=timezone.now())

    response = await attach(async_client, user, channel.id, file)

    await assert_error(response, 404, "channel_not_found")
    assert not await is_attached(file)


# --- request and token ---


@pytest.mark.parametrize(
    ("file_ids", "fields"),
    [
        ([], {"file_ids": "too_short"}),
        ([str(uuid.uuid4()) for _ in range(11)], {"file_ids": "too_long"}),
        (["6f1c2a9e-0000-4000-8000-000000000001"] * 2, {"file_ids": "invalid"}),
        (["not-a-uuid"], {"file_ids.0": "invalid"}),
    ],
    ids=["empty", "eleven", "duplicate", "not_a_uuid"],
)
async def test_invalid_file_ids(async_client, user, channel, file_ids, fields):
    body = {"user_id": str(user.id), "channel_id": str(channel.id), "file_ids": file_ids}

    response = await async_client.post(
        "/internal/files/attach", body, content_type="application/json", headers=SERVICE
    )

    await assert_error(response, 400, "validation_error")
    assert response.json()["error"]["fields"] == fields


@pytest.mark.parametrize("token", [None, "wrong"])
async def test_service_token_is_needed(async_client, user, team, channel, token):
    file = await make_file(user, "attachment", team)
    headers = {} if token is None else {"X-Service-Token": token}

    response = await attach(async_client, user, channel.id, file, headers=headers)

    await assert_error(response, 401, "invalid_service_token")
    assert not await is_attached(file)


async def test_a_users_token_is_not_enough(async_client, user, auth, team, channel):
    file = await make_file(user, "attachment", team)

    response = await attach(async_client, user, channel.id, file, headers=auth)

    await assert_error(response, 401, "invalid_service_token")


# --- after attach ---


async def test_attached_file_cant_be_deleted_by_its_owner(async_client, user, team, channel):
    file = await make_file(user, "attachment", team)
    await attach(async_client, user, channel.id, file)

    response = await async_client.delete(
        f"/api/core/v1/files/{file.id}", headers=await headers_for(user)
    )

    await assert_error(response, 409, "file_attached")
    assert await is_attached(file)
