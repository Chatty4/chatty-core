from django.urls import path

from users.internal.views import MembershipsView

urlpatterns = [
    path(
        "users/<uuid:user_id>/memberships",
        MembershipsView.as_view(),
        name="internal-user-memberships",
    ),
]
