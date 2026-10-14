from django.urls import path

from teams.views import TeamDetailView, TeamsView

urlpatterns = [
    path("teams", TeamsView.as_view(), name="teams"),
    path("teams/<uuid:team_id>", TeamDetailView.as_view(), name="team-detail"),
]
