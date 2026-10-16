import pytest
from asgiref.sync import sync_to_async

from users.models import User
from users.repositories import UserRepository

pytestmark = pytest.mark.django_db(transaction=True)

ADD_URL = "/admin/users/user/add/"
PASSWORD = "correct horse battery"


async def test_create_user_lowercases_email():
    user = await sync_to_async(User.objects.create_user)(
        email="Bob@Example.COM", display_name="Bob", password=PASSWORD
    )

    assert user.email == "bob@example.com"


async def test_superuser_with_mixed_case_email_is_found_by_login_lookup():
    await sync_to_async(User.objects.create_superuser)(
        email="Bob@Example.COM", display_name="Bob", password=PASSWORD
    )

    assert await UserRepository.get_by_email("bob@example.com") is not None


async def add_user_in_admin(async_client, email: str):
    staff = await User.objects.acreate(email="admin@example.com", display_name="A", is_staff=True)
    await async_client.aforce_login(staff)
    return await async_client.post(
        ADD_URL,
        {
            "email": email,
            "display_name": "Carl",
            "password1": PASSWORD,
            "password2": PASSWORD,
            "usable_password": "true",
        },
    )


async def test_admin_add_user_lowercases_email(async_client):
    response = await add_user_in_admin(async_client, "Carl@Example.COM")

    assert response.status_code == 302
    assert await User.objects.filter(email="carl@example.com").aexists()


async def test_admin_add_user_rejects_case_only_duplicate(async_client):
    await User.objects.acreate(email="carl@example.com", display_name="Carl")

    response = await add_user_in_admin(async_client, "Carl@Example.COM")

    assert response.status_code == 200  # form shown again with the error
    assert await User.objects.filter(email__iexact="carl@example.com").acount() == 1
