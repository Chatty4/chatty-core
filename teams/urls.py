from django.urls import path

from teams.views import TeamsView

urlpatterns = [
    path("teams", TeamsView.as_view(), name="teams"),
]
