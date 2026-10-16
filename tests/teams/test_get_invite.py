from datetime import timedelta

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from shared.redis import clear_rate_limit, get_redis_client
from teams.models import Invite, Team, TeamMember
from users.models import User

pytestmark = pytest.mark.django_db(transaction=True)

RATE_KEY = "invite_lookup:127.0.0.1"


@pytest.fixture(autouse=True)
async def redis_client():
    get_redis_client.cache_clear()
    await clear_rate_limit(RATE_KEY)
    yield
    await clear_rate_limit(RATE_KEY)
    await get_redis_client().aclose()
    get_redis_client.cache_clear()


@pytest.fixture
async def owner():
    return await sync_to_async(User.objects.create_user)(
        email="ana@example.com", display_name="Ana Pop", password="correct horse battery"
    )


@pytest.fixture
async def team(owner):
    t = await Team.objects.acreate(name="Backend", created_by=owner)
    await TeamMember.objects.acreate(team=t, user=owner, role=TeamMember.Role.OWNER)
    return t


@pytest.fixture
async def invite(team, owner):
    return await Invite.objects.acreate(
        team=team, created_by=owner, code="abcd1234", max_uses=0, uses=0
    )


def url(code):
    return f"/api/core/v1/invites/{code}"


# --- status and shape ---


async def test_get_invite_returns_200(async_client, invite):
    response = await async_client.get(url(invite.code))

    assert response.status_code == 200


async def test_get_invite_response_shape(async_client, invite):
    response = await async_client.get(url(invite.code))

    body = response.json()
    assert "code" in body
    assert "valid" in body
    assert "reason" in body
    assert "expires_at" in body
    assert "name" in body["team"]
    assert "icon_url" in body["team"]
    assert "member_count" in body["team"]


async def test_get_invite_code_matches(async_client, invite):
    body = (await async_client.get(url(invite.code))).json()

    assert body["code"] == invite.code


# --- valid invite ---


async def test_get_invite_valid_true(async_client, invite):
    body = (await async_client.get(url(invite.code))).json()

    assert body["valid"] is True
    assert body["reason"] is None


# --- invalid invites still return 200 ---


async def test_get_invite_revoked_returns_200(async_client, team, owner):
    inv = await Invite.objects.acreate(
        team=team,
        created_by=owner,
        code="revoked1",
        max_uses=0,
        uses=0,
        revoked_at=timezone.now(),
    )

    response = await async_client.get(url(inv.code))

    assert response.status_code == 200


async def test_get_invite_revoked_is_invalid(async_client, team, owner):
    inv = await Invite.objects.acreate(
        team=team,
        created_by=owner,
        code="revoked1",
        max_uses=0,
        uses=0,
        revoked_at=timezone.now(),
    )

    body = (await async_client.get(url(inv.code))).json()

    assert body["valid"] is False
    assert body["reason"] == "revoked"


async def test_get_invite_expired_is_invalid(async_client, team, owner):
    inv = await Invite.objects.acreate(
        team=team,
        created_by=owner,
        code="expired1",
        max_uses=0,
        uses=0,
        expires_at=timezone.now() - timedelta(seconds=1),
    )

    body = (await async_client.get(url(inv.code))).json()

    assert body["valid"] is False
    assert body["reason"] == "expired"


async def test_get_invite_used_up_is_invalid(async_client, team, owner):
    inv = await Invite.objects.acreate(
        team=team,
        created_by=owner,
        code="usedup01",
        max_uses=5,
        uses=5,
    )

    body = (await async_client.get(url(inv.code))).json()

    assert body["valid"] is False
    assert body["reason"] == "used_up"


# --- team info ---


async def test_get_invite_team_name(async_client, invite, team):
    body = (await async_client.get(url(invite.code))).json()

    assert body["team"]["name"] == team.name


async def test_get_invite_team_icon_url_is_null(async_client, invite):
    body = (await async_client.get(url(invite.code))).json()

    assert body["team"]["icon_url"] is None


async def test_get_invite_team_member_count(async_client, invite, team):
    body = (await async_client.get(url(invite.code))).json()

    assert body["team"]["member_count"] == 1


async def test_get_invite_team_member_count_includes_all_members(async_client, invite, team):
    extra = await sync_to_async(User.objects.create_user)(
        email="bob@example.com", display_name="Bob Pop", password="correct horse battery"
    )
    await TeamMember.objects.acreate(team=team, user=extra, role=TeamMember.Role.MEMBER)

    body = (await async_client.get(url(invite.code))).json()

    assert body["team"]["member_count"] == 2


# --- expires_at ---


async def test_get_invite_expires_at_null_when_no_expiry(async_client, team, owner):
    inv = await Invite.objects.acreate(
        team=team,
        created_by=owner,
        code="noexpiry",
        max_uses=0,
        uses=0,
        expires_at=None,
    )

    body = (await async_client.get(url(inv.code))).json()

    assert body["expires_at"] is None


async def test_get_invite_expires_at_set(async_client, team, owner):
    inv = await Invite.objects.acreate(
        team=team,
        created_by=owner,
        code="expires1",
        max_uses=0,
        uses=0,
        expires_at=timezone.now() + timedelta(days=7),
    )

    body = (await async_client.get(url(inv.code))).json()

    assert body["expires_at"] is not None


# --- not found ---


async def test_get_invite_unknown_code_returns_404(async_client):
    response = await async_client.get(url("notfound"))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "invite_not_found"


async def test_get_invite_deleted_team_returns_404(async_client, invite, team):
    team.deleted_at = timezone.now()
    await team.asave(update_fields=["deleted_at"])

    response = await async_client.get(url(invite.code))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "invite_not_found"


# --- no auth required ---


async def test_get_invite_no_auth_required(async_client, invite):
    response = await async_client.get(url(invite.code))

    assert response.status_code == 200


# --- rate limit ---


async def test_get_invite_rate_limited_after_30(async_client):
    for _ in range(30):
        await async_client.get(url("doesntexist"))

    response = await async_client.get(url("doesntexist"))

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"
    assert int(response["Retry-After"]) > 0
