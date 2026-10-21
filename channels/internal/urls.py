from django.urls import path

from channels.internal.views import InternalChannelView

urlpatterns = [
    path("channels/<uuid:channel_id>", InternalChannelView.as_view(), name="internal-channel"),
]
