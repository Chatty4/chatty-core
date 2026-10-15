from django.urls import path

from channels.views import BrowseChannelsView, TeamChannelsView

urlpatterns = [
    path("teams/<uuid:team_id>/channels", TeamChannelsView.as_view(), name="team-channels"),
    path(
        "teams/<uuid:team_id>/channels/browse",
        BrowseChannelsView.as_view(),
        name="team-channels-browse",
    ),
]
