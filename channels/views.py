from uuid import UUID

from rest_framework.response import Response

from channels.serializers import ChannelResponse, CreateChannelRequest, MyChannelResponse
from channels.services import ChannelService
from shared.serializers import validated
from shared.views import UserAPIView


class TeamChannelsView(UserAPIView):
    async def get(self, request, team_id: UUID):
        channels = await ChannelService.list_mine(team_id, request.user.id)
        return Response({"channels": MyChannelResponse(channels, many=True).data})

    async def post(self, request, team_id: UUID):
        data = validated(CreateChannelRequest, request.data)
        channel = await ChannelService.create(team_id, request.user.id, **data)
        return Response(ChannelResponse(channel).data, status=201)
