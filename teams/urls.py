from django.urls import path

from teams.views import (
    InviteDetailView,
    InviteLookupView,
    LeaveTeamView,
    TeamDetailView,
    TeamInvitesView,
    TeamMemberDetailView,
    TeamMembersView,
    TeamsView,
)

urlpatterns = [
    path("teams", TeamsView.as_view(), name="teams"),
    path("teams/<uuid:team_id>", TeamDetailView.as_view(), name="team-detail"),
    path("teams/<uuid:team_id>/leave", LeaveTeamView.as_view(), name="team-leave"),
    path("teams/<uuid:team_id>/invites", TeamInvitesView.as_view(), name="team-invites"),
    path("invites/<uuid:invite_id>", InviteDetailView.as_view(), name="invite-detail"),
    path("invites/<str:invite_code>", InviteLookupView.as_view(), name="invite-lookup"),
    path("teams/<uuid:team_id>/members", TeamMembersView.as_view(), name="team-members"),
    path(
        "teams/<uuid:team_id>/members/<uuid:user_id>",
        TeamMemberDetailView.as_view(),
        name="team-member-detail",
    ),
]
