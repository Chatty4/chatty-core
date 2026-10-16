from django.urls import path

from channels.views import (
    BrowseChannelsView,
    ChannelDetailView,
    ChannelMembersView,
    JoinChannelView,
    LeaveChannelView,
    TeamChannelsView,
)

urlpatterns = [
    path("channels/<uuid:channel_id>", ChannelDetailView.as_view(), name="channel-detail"),
    path("channels/<uuid:channel_id>/join", JoinChannelView.as_view(), name="channel-join"),
    path("channels/<uuid:channel_id>/leave", LeaveChannelView.as_view(), name="channel-leave"),
    path(
        "channels/<uuid:channel_id>/members", ChannelMembersView.as_view(), name="channel-members"
    ),
    path("teams/<uuid:team_id>/channels", TeamChannelsView.as_view(), name="team-channels"),
    path(
        "teams/<uuid:team_id>/channels/browse",
        BrowseChannelsView.as_view(),
        name="team-channels-browse",
    ),
]
