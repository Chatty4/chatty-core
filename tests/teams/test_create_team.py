import pytest
from asgiref.sync import sync_to_async

from authn.services import AuthnService
from channels.models import Channel, ChannelMember
from teams.models import Team, TeamMember
from users.models import User

pytestmark = pytest.mark.django_db(transaction=True)

URL = "/api/core/v1/teams"


@pytest.fixture
async def user():
    return await sync_to_async(User.objects.create_user)(
        email="ana@example.com", display_name="Ana Pop", password="correct horse battery"
    )


@pytest.fixture
async def auth(user):
    tokens = await AuthnService().issue_tokens(user)
    return {"Authorization": f"Bearer {tokens.access_token}"}


async def post_teams(client, body, headers):
    return await client.post(URL, body, content_type="application/json", headers=headers)


async def test_create_team_returns_201(async_client, user, auth):
    response = await post_teams(async_client, {"name": "Backend"}, auth)

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Backend"
    assert body["icon_file_id"] is None
    assert body["role"] == "owner"
    assert body["member_count"] == 1
    assert body["id"]
    assert body["general_channel_id"]
    assert body["created_at"]


async def test_create_team_persists_db_objects(async_client, user, auth):
    response = await post_teams(async_client, {"name": "Backend"}, auth)

    assert response.status_code == 201
    body = response.json()
    team_id = body["id"]
    channel_id = body["general_channel_id"]

    team = await Team.objects.aget(id=team_id)
    assert team.name == "Backend"
    assert str(team.created_by_id) == str(user.id)  # type: ignore

    member = await TeamMember.objects.aget(team_id=team_id, user_id=user.id)
    assert member.role == TeamMember.Role.OWNER

    channel = await Channel.objects.aget(id=channel_id)
    assert channel.name == "general"
    assert channel.kind == Channel.Kind.PUBLIC
    assert channel.is_default is True

    channel_member = await ChannelMember.objects.aget(channel_id=channel_id, user_id=user.id)
    assert channel_member.role == ChannelMember.Role.OWNER
    assert channel_member.notify_level == ChannelMember.NotifyLevel.MENTIONS


async def test_create_team_requires_auth(async_client):
    response = await post_teams(async_client, {"name": "Backend"}, {})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_create_team_inactive_user(async_client, user, auth):
    user.is_active = False
    await user.asave(update_fields=["is_active"])

    response = await post_teams(async_client, {"name": "Backend"}, auth)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "user_inactive"


async def test_create_team_name_missing(async_client, auth):
    response = await post_teams(async_client, {}, auth)

    assert response.status_code == 400
    assert response.json()["error"]["fields"]["name"] == "required"


async def test_create_team_name_blank(async_client, auth):
    response = await post_teams(async_client, {"name": ""}, auth)

    assert response.status_code == 400
    assert response.json()["error"]["fields"]["name"] == "blank"


async def test_create_team_name_too_long(async_client, auth):
    response = await post_teams(async_client, {"name": "x" * 81}, auth)

    assert response.status_code == 400
    assert response.json()["error"]["fields"]["name"] == "too_long"


async def test_create_team_limit_reached(async_client, user, auth):
    await sync_to_async(Team.objects.bulk_create)(
        [Team(name=f"Team {i}", created_by=user) for i in range(10)]
    )

    response = await post_teams(async_client, {"name": "One Too Many"}, auth)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "team_limit_reached"


async def test_create_team_limit_ignores_other_users_teams(async_client, user, auth):
    other = await sync_to_async(User.objects.create_user)(
        email="other@example.com", display_name="Other", password="correct horse battery"
    )
    await sync_to_async(Team.objects.bulk_create)(
        [Team(name=f"Team {i}", created_by=other) for i in range(10)]
    )

    response = await post_teams(async_client, {"name": "My Team"}, auth)

    assert response.status_code == 201


async def test_create_team_limit_ignores_deleted_teams(async_client, user, auth):
    from django.utils import timezone

    await sync_to_async(Team.objects.bulk_create)(
        [Team(name=f"Team {i}", created_by=user, deleted_at=timezone.now()) for i in range(10)]
    )

    response = await post_teams(async_client, {"name": "Fresh Team"}, auth)

    assert response.status_code == 201
