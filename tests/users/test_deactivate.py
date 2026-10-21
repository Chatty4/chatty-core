from dataclasses import asdict

import pytest

from authn.models import RefreshToken
from authn.services import AuthnService
from shared.events import EventType
from users.models import User
from users.schemas import UserDeactivated
from users.services import UserService

# transaction=True: same reason as test_register.py (writes go through another DB connection)
pytestmark = pytest.mark.django_db(transaction=True)

CHANGELIST = "/admin/users/user/"


async def make_user(email, **fields):
    return await User.objects.acreate(email=email, display_name="Test", **fields)


async def live_tokens(user):
    return await RefreshToken.objects.filter(user=user, revoked_at__isnull=True).acount()


async def test_deactivate_returns_only_users_that_were_active():
    active = await make_user("a@example.com")
    inactive = await make_user("b@example.com", is_active=False)

    deactivated = await UserService.deactivate([active.id, inactive.id])

    assert deactivated == [active.id]
    await active.arefresh_from_db()
    assert active.is_active is False


async def test_deactivate_leaves_other_users_active():
    target = await make_user("a@example.com")
    other = await make_user("b@example.com")

    await UserService.deactivate([target.id])

    await other.arefresh_from_db()
    assert other.is_active is True


async def test_admin_action_deactivates_selected_users(async_client):
    staff = await make_user("admin@example.com", is_staff=True)
    target = await make_user("ana@example.com")
    await async_client.aforce_login(staff)

    response = await async_client.post(
        CHANGELIST, {"action": "deactivate", "_selected_action": [str(target.id)]}
    )

    assert response.status_code == 302
    await target.arefresh_from_db()
    assert target.is_active is False


async def test_admin_form_cannot_change_is_active(async_client):
    # deactivation must go through the action (and later its event), not the edit form
    staff = await make_user("admin@example.com", is_staff=True)
    target = await make_user("ana@example.com")
    await async_client.aforce_login(staff)

    response = await async_client.get(f"{CHANGELIST}{target.id}/change/")

    assert response.status_code == 200
    assert 'name="is_active"' not in response.content.decode()


async def test_deactivate_revokes_all_refresh_tokens():
    user = await make_user("a@example.com")
    await AuthnService().issue_tokens(user)  # phone
    await AuthnService().issue_tokens(user)  # laptop

    await UserService.deactivate([user.id])

    assert await live_tokens(user) == 0


async def test_deactivate_keeps_other_users_tokens():
    target = await make_user("a@example.com")
    other = await make_user("b@example.com")
    await AuthnService().issue_tokens(target)
    await AuthnService().issue_tokens(other)

    await UserService.deactivate([target.id])

    assert await live_tokens(other) == 1


async def test_deactivate_cleans_tokens_of_already_inactive_user():
    # deactivated before this fix: inactive, but with a live token left behind
    user = await make_user("a@example.com")
    await AuthnService().issue_tokens(user)
    await User.objects.filter(id=user.id).aupdate(is_active=False)

    deactivated = await UserService.deactivate([user.id])

    assert deactivated == []  # no new deactivation, so no future event
    assert await live_tokens(user) == 0


# --- user.deactivated event ---


async def test_deactivate_publishes_only_for_users_that_were_active(published):
    active = await make_user("a@example.com")
    inactive = await make_user("b@example.com", is_active=False)

    await UserService.deactivate([active.id, inactive.id])

    deactivations = [e for e in published if e[0] == EventType.USER_DEACTIVATED]
    assert deactivations == [(EventType.USER_DEACTIVATED, asdict(UserDeactivated(active.id)))]


async def test_admin_action_publishes_user_deactivated(async_client, published):
    staff = await make_user("admin@example.com", is_staff=True)
    target = await make_user("ana@example.com")
    await async_client.aforce_login(staff)

    await async_client.post(
        CHANGELIST, {"action": "deactivate", "_selected_action": [str(target.id)]}
    )

    assert (EventType.USER_DEACTIVATED, asdict(UserDeactivated(target.id))) in published
