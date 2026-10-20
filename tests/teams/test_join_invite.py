from datetime import timedelta

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from authn.services import AuthnService
from channels.models import Channel, ChannelMember
from shared.exceptions import NotFound
from shared.redis import clear_rate_limit, get_redis_client
from teams.models import Invite, Team, TeamMember
from teams.services import InviteService
from users.models import User

RATE_KEY = "invite_lookup:127.0.0.1"

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
async def owner():
    return await sync_to_async(User.objects.create_user)(
        email="ana@example.com", display_name="Ana Pop", password="correct horse battery"
    )


@pytest.fixture
async def joiner():
    return await sync_to_async(User.objects.create_user)(
        email="bob@example.com", display_name="Bob Pop", password="correct horse battery"
    )


@pytest.fixture
async def owner_auth(owner):
    tokens = await AuthnService().issue_tokens(owner)
    return {"Authorization": f"Bearer {tokens.access_token}"}


@pytest.fixture
async def joiner_auth(joiner):
    tokens = await AuthnService().issue_tokens(joiner)
    return {"Authorization": f"Bearer {tokens.access_token}"}


@pytest.fixture
async def team(owner):
    t = await Team.objects.acreate(name="Backend", created_by=owner)
    await TeamMember.objects.acreate(team=t, user=owner, role=TeamMember.Role.OWNER)
    return t


@pytest.fixture
async def general(team, owner):
    return await Channel.objects.acreate(
        team=team, name="general", kind=Channel.Kind.PUBLIC, is_default=True, created_by=owner
    )


@pytest.fixture
async def invite(team, owner, general):
    return await Invite.objects.acreate(
        team=team, created_by=owner, code="joininv1", max_uses=0, uses=0
    )


@pytest.fixture(autouse=True)
async def redis_client():
    get_redis_client.cache_clear()
    await clear_rate_limit(RATE_KEY)
    yield
    await clear_rate_limit(RATE_KEY)
    await get_redis_client().aclose()
    get_redis_client.cache_clear()


def url(code):
    return f"/api/core/v1/invites/{code}/join"


# --- status and shape ---


async def test_join_returns_201(async_client, invite, joiner_auth):
    response = await async_client.post(url(invite.code), headers=joiner_auth)

    assert response.status_code == 201


async def test_join_response_body(async_client, invite, team, general, joiner_auth):
    body = (await async_client.post(url(invite.code), headers=joiner_auth)).json()

    assert body == {
        "team_id": str(team.id),
        "name": "Backend",
        "role": "member",
        "already_member": False,
        "channel_ids": [str(general.id)],
    }


# --- DB state ---


async def test_join_creates_team_member(async_client, invite, team, joiner, joiner_auth):
    await async_client.post(url(invite.code), headers=joiner_auth)

    member = await TeamMember.objects.aget(team=team, user=joiner)
    assert member.role == TeamMember.Role.MEMBER


async def test_join_clears_leftover_channel_rows(
    async_client, invite, team, owner, general, joiner, joiner_auth
):
    # A channel add that raced with a team removal left this row behind
    secret = await Channel.objects.acreate(
        team=team, name="secret", kind=Channel.Kind.PRIVATE, created_by=owner
    )
    await ChannelMember.objects.acreate(
        channel=secret, user=joiner, notify_level=ChannelMember.NotifyLevel.ALL
    )

    response = await async_client.post(url(invite.code), headers=joiner_auth)

    assert response.status_code == 201
    assert response.json()["channel_ids"] == [str(general.id)]
    assert not await ChannelMember.objects.filter(channel=secret, user=joiner).aexists()
    joined = [
        cid
        async for cid in ChannelMember.objects.filter(user=joiner).values_list(
            "channel_id", flat=True
        )
    ]
    assert joined == [general.id]


async def test_join_adds_user_to_default_channel(
    async_client, invite, general, joiner, joiner_auth
):
    await async_client.post(url(invite.code), headers=joiner_auth)

    cm = await ChannelMember.objects.aget(channel=general, user=joiner)
    assert cm.role == ChannelMember.Role.MEMBER
    assert cm.notify_level == ChannelMember.NotifyLevel.MENTIONS


async def test_join_with_leftover_channel_membership(
    async_client, invite, general, joiner, joiner_auth
):
    # A channel row left behind when a channel join raced with removal from the team.
    await ChannelMember.objects.acreate(
        channel=general, user=joiner, notify_level=ChannelMember.NotifyLevel.MENTIONS
    )

    response = await async_client.post(url(invite.code), headers=joiner_auth)

    assert response.status_code == 201
    assert await ChannelMember.objects.filter(channel=general, user=joiner).acount() == 1


async def test_join_adds_user_to_every_default_channel(
    async_client, invite, team, owner, general, joiner, joiner_auth
):
    news = await Channel.objects.acreate(
        team=team, name="news", kind=Channel.Kind.PUBLIC, is_default=True, created_by=owner
    )

    body = (await async_client.post(url(invite.code), headers=joiner_auth)).json()

    assert set(body["channel_ids"]) == {str(general.id), str(news.id)}
    assert await ChannelMember.objects.filter(user=joiner).acount() == 2


async def test_join_skips_non_default_channel(
    async_client, invite, team, owner, joiner, joiner_auth
):
    random = await Channel.objects.acreate(
        team=team, name="random", kind=Channel.Kind.PUBLIC, is_default=False, created_by=owner
    )

    body = (await async_client.post(url(invite.code), headers=joiner_auth)).json()

    assert str(random.id) not in body["channel_ids"]
    assert not await ChannelMember.objects.filter(channel=random, user=joiner).aexists()


async def test_join_skips_archived_default_channel(
    async_client, invite, team, owner, joiner, joiner_auth
):
    old = await Channel.objects.acreate(
        team=team,
        name="old",
        kind=Channel.Kind.PUBLIC,
        is_default=True,
        created_by=owner,
        archived_at=timezone.now(),
    )

    body = (await async_client.post(url(invite.code), headers=joiner_auth)).json()

    assert str(old.id) not in body["channel_ids"]
    assert not await ChannelMember.objects.filter(channel=old, user=joiner).aexists()


async def test_join_increments_uses(async_client, invite, joiner_auth):
    await async_client.post(url(invite.code), headers=joiner_auth)

    await invite.arefresh_from_db()
    assert invite.uses == 1


async def test_join_last_use_of_limited_invite(async_client, team, owner, general, joiner_auth):
    inv = await Invite.objects.acreate(
        team=team, created_by=owner, code="lastuse1", max_uses=2, uses=1
    )

    response = await async_client.post(url(inv.code), headers=joiner_auth)

    assert response.status_code == 201
    await inv.arefresh_from_db()
    assert inv.uses == 2


# --- already a member ---


async def test_join_already_member_returns_200(async_client, invite, owner_auth):
    response = await async_client.post(url(invite.code), headers=owner_auth)

    assert response.status_code == 200


async def test_join_already_member_response_body(async_client, invite, team, owner_auth):
    body = (await async_client.post(url(invite.code), headers=owner_auth)).json()

    assert body == {
        "team_id": str(team.id),
        "name": "Backend",
        "role": "owner",
        "already_member": True,
        "channel_ids": [],
    }


async def test_join_already_member_does_not_increment_uses(async_client, invite, owner_auth):
    await async_client.post(url(invite.code), headers=owner_auth)

    await invite.arefresh_from_db()
    assert invite.uses == 0


async def test_join_twice_second_is_already_member(async_client, invite, joiner_auth):
    await async_client.post(url(invite.code), headers=joiner_auth)

    response = await async_client.post(url(invite.code), headers=joiner_auth)

    assert response.status_code == 200
    assert response.json()["already_member"] is True
    await invite.arefresh_from_db()
    assert invite.uses == 1


async def test_join_already_member_with_invalid_invite_returns_200(
    async_client, team, owner, general, owner_auth
):
    inv = await Invite.objects.acreate(
        team=team,
        created_by=owner,
        code="expmine1",
        max_uses=0,
        uses=0,
        expires_at=timezone.now() - timedelta(seconds=1),
    )

    response = await async_client.post(url(inv.code), headers=owner_auth)

    assert response.status_code == 200
    assert response.json()["already_member"] is True


# --- invalid invite: 410 ---


async def test_join_revoked_returns_410(async_client, team, owner, general, joiner_auth):
    inv = await Invite.objects.acreate(
        team=team,
        created_by=owner,
        code="revoked1",
        max_uses=0,
        uses=0,
        revoked_at=timezone.now(),
    )

    response = await async_client.post(url(inv.code), headers=joiner_auth)

    assert response.status_code == 410
    assert response.json()["error"]["code"] == "invite_invalid"
    assert response.json()["error"]["message"] == "revoked"


async def test_join_expired_returns_410(async_client, team, owner, general, joiner_auth):
    inv = await Invite.objects.acreate(
        team=team,
        created_by=owner,
        code="expired1",
        max_uses=0,
        uses=0,
        expires_at=timezone.now() - timedelta(seconds=1),
    )

    response = await async_client.post(url(inv.code), headers=joiner_auth)

    assert response.status_code == 410
    assert response.json()["error"]["code"] == "invite_invalid"
    assert response.json()["error"]["message"] == "expired"


async def test_join_used_up_returns_410(async_client, team, owner, general, joiner_auth):
    inv = await Invite.objects.acreate(
        team=team, created_by=owner, code="usedup01", max_uses=1, uses=1
    )

    response = await async_client.post(url(inv.code), headers=joiner_auth)

    assert response.status_code == 410
    assert response.json()["error"]["code"] == "invite_invalid"
    assert response.json()["error"]["message"] == "used_up"


async def test_join_invalid_invite_changes_nothing(
    async_client, team, owner, general, joiner, joiner_auth
):
    inv = await Invite.objects.acreate(
        team=team, created_by=owner, code="usedup02", max_uses=1, uses=1
    )

    await async_client.post(url(inv.code), headers=joiner_auth)

    assert not await TeamMember.objects.filter(team=team, user=joiner).aexists()
    assert not await ChannelMember.objects.filter(user=joiner).aexists()
    await inv.arefresh_from_db()
    assert inv.uses == 1


async def test_join_single_use_invite_rejects_second_user(
    async_client, team, owner, general, joiner_auth
):
    inv = await Invite.objects.acreate(
        team=team, created_by=owner, code="single01", max_uses=1, uses=0
    )
    other = await sync_to_async(User.objects.create_user)(
        email="cara@example.com", display_name="Cara Pop", password="correct horse battery"
    )
    other_tokens = await AuthnService().issue_tokens(other)
    other_auth = {"Authorization": f"Bearer {other_tokens.access_token}"}

    first = await async_client.post(url(inv.code), headers=joiner_auth)
    second = await async_client.post(url(inv.code), headers=other_auth)

    assert first.status_code == 201
    assert second.status_code == 410
    assert second.json()["error"]["message"] == "used_up"


# --- not found ---


async def test_join_unknown_code_returns_404(async_client, joiner_auth):
    response = await async_client.post(url("notfound"), headers=joiner_auth)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "invite_not_found"


async def test_join_deleted_team_returns_404(async_client, invite, team, joiner_auth):
    team.deleted_at = timezone.now()
    await team.asave(update_fields=["deleted_at"])

    response = await async_client.post(url(invite.code), headers=joiner_auth)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "invite_not_found"


async def test_join_stops_if_team_was_deleted_meanwhile(invite, team, joiner):
    # the invite was looked up, then the owner deleted the team before the join's transaction
    await Team.objects.filter(id=team.id).aupdate(deleted_at=timezone.now())

    with pytest.raises(NotFound):
        await sync_to_async(InviteService._join_sync)(invite.id, team, joiner.id)

    assert not await TeamMember.objects.filter(team=team, user=joiner).aexists()


# --- auth ---


async def test_join_requires_auth(async_client, invite):
    response = await async_client.post(url(invite.code))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


# --- rate limit ---


async def test_join_shares_the_lookup_rate_limit(async_client, joiner_auth):
    for _ in range(30):
        await async_client.get("/api/core/v1/invites/nosuchcd")

    response = await async_client.post("/api/core/v1/invites/nosuchcd/join", headers=joiner_auth)

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"
