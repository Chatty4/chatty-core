from django.urls import path

from teams.views import TeamDetailView, TeamMembersView, TeamsView

urlpatterns = [
    path("teams", TeamsView.as_view(), name="teams"),
    path("teams/<uuid:team_id>", TeamDetailView.as_view(), name="team-detail"),
    path("teams/<uuid:team_id>/members", TeamMembersView.as_view(), name="team-members"),
]
