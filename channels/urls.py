from django.urls import path

from channels.views import TeamChannelsView

urlpatterns = [
    path("teams/<uuid:team_id>/channels", TeamChannelsView.as_view(), name="team-channels"),
]