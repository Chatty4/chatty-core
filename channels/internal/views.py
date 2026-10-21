from uuid import UUID

from rest_framework.response import Response

from channels.internal.serializers import InternalChannelResponse
from channels.services import ChannelService
from shared.views import InternalAPIView


class InternalChannelView(InternalAPIView):
    async def get(self, request, channel_id: UUID):
        channel = await ChannelService.get_internal(channel_id)
        return Response(InternalChannelResponse(channel).data)
