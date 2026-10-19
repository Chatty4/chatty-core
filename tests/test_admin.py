import pytest
from django.contrib import admin

from channels.models import ChannelMember
from teams.models import TeamMember
from users.models import User

pytestmark = pytest.mark.django_db


@pytest.fixture
def request_as_staff(rf):
    request = rf.get("/admin/")
    request.user = User.objects.create_superuser(
        email="admin@example.com", display_name="Admin", password="correct horse battery"
    )
    return request


def test_staff_cannot_delete_users(request_as_staff):
    assert not admin.site._registry[User].has_delete_permission(request_as_staff)


@pytest.mark.parametrize("model", [TeamMember, ChannelMember])
def test_memberships_are_view_only(request_as_staff, model):
    model_admin = admin.site._registry[model]
    assert model_admin.has_view_permission(request_as_staff)
    assert not model_admin.has_add_permission(request_as_staff)
    assert not model_admin.has_change_permission(request_as_staff)
    assert not model_admin.has_delete_permission(request_as_staff)
