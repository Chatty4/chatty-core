import pytest

from users.models import User
from users.services import UserService

# transaction=True: same reason as test_register.py (writes go through another DB connection)
pytestmark = pytest.mark.django_db(transaction=True)

CHANGELIST = "/admin/users/user/"


async def make_user(email, **fields):
    return await User.objects.acreate(email=email, display_name="Test", **fields)


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
