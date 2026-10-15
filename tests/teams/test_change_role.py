import uuid

import pytest
from asgiref.sync import sync_to_async

from authn.services import AuthnService
from teams.models import TeamMember
from teams.services import TeamService
from users.models import User

pytestmark = pytest.mark.django_db(transaction=True)

OWNER, ADMIN, MEMBER = TeamMember.Role.OWNER, TeamMember.Role.ADMIN, TeamMember.Role.MEMBER


async def make_user(email: str) -> User:
    return await sync_to_async(User.objects.create_user)(
        email=email, display_name="Ana Pop", password="correct horse battery"
    )


async def headers_for(user: User) -> dict:
    tokens = await AuthnService().issue_tokens(user)
    return {"Authorization": f"Bearer {tokens.access_token}"}


async def join(team, role: str) -> User:
    user = await make_user(f"{uuid.uuid4().hex}@example.com")
    await TeamMember.objects.acreate(team_id=team.id, user=user, role=role)
    return user


@pytest.fixture
async def owner():
    return await make_user("owner@example.com")


@pytest.fixture
async def team(owner):
    return await TeamService.create("Backend", owner.id)


async def put_role(client, team, target, role, as_user):
    return await client.put(
        f"/api/core/v1/teams/{team.id}/members/{target.id}",
        {"role": role},
        content_type="application/json",
        headers=await headers_for(as_user),
    )


async def role_of(team, user) -> str:
    return (await TeamMember.objects.aget(team_id=team.id, user=user)).role


async def test_owner_promotes_member_to_admin(async_client, owner, team):
    member = await join(team, MEMBER)

    response = await put_role(async_client, team, member, ADMIN, owner)

    assert response.status_code == 200
    assert response.json() == {"user_id": str(member.id), "team_id": str(team.id), "role": "admin"}
    assert await role_of(team, member) == ADMIN


async def test_admin_can_switch_member_and_admin(async_client, team):
    admin = await join(team, ADMIN)
    member = await join(team, MEMBER)

    response = await put_role(async_client, team, member, ADMIN, admin)

    assert response.status_code == 200


async def test_owner_can_make_another_owner(async_client, owner, team):
    member = await join(team, MEMBER)

    response = await put_role(async_client, team, member, OWNER, owner)

    assert response.status_code == 200
    assert await role_of(team, member) == OWNER


@pytest.mark.parametrize(
    ("caller_role", "target_role", "new_role"),
    [
        (MEMBER, MEMBER, ADMIN),  # members can't change roles
        (ADMIN, MEMBER, OWNER),  # admins can't make owners
        (ADMIN, OWNER, MEMBER),  # admins can't change owners
    ],
)
async def test_forbidden_changes(async_client, team, caller_role, target_role, new_role):
    caller = await join(team, caller_role)
    target = await join(team, target_role)

    response = await put_role(async_client, team, target, new_role, caller)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
    assert await role_of(team, target) == target_role


async def test_target_outside_the_team_is_not_found(async_client, owner, team):
    outsider = await make_user("out@example.com")

    response = await put_role(async_client, team, outsider, ADMIN, owner)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "member_not_found"


async def test_only_owner_cant_demote_themselves(async_client, owner, team):
    response = await put_role(async_client, team, owner, ADMIN, owner)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "last_owner"
    assert await role_of(team, owner) == OWNER


async def test_owner_can_step_down_when_another_owner_exists(async_client, owner, team):
    await join(team, OWNER)

    response = await put_role(async_client, team, owner, MEMBER, owner)

    assert response.status_code == 200
    assert await role_of(team, owner) == MEMBER


async def test_unknown_role_is_rejected(async_client, owner, team):
    member = await join(team, MEMBER)

    response = await put_role(async_client, team, member, "king", owner)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"