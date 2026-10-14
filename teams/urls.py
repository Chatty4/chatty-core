from django.urls import path

from teams.views import CreateTeamView

urlpatterns = [
    path("teams", CreateTeamView.as_view(), name="teams"),
]
