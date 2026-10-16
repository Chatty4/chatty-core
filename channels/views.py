from uuid import UUID

from rest_framework.response import Response

from channels.serializers import (
    BrowseChannelResponse,
    BrowseChannelsQuery,
    ChannelDetailResponse,
    ChannelMemberResponse,
    ChannelResponse,
    CreateChannelRequest,
    JoinChannelResponse,
    MyChannelResponse,
)
from channels.services import ChannelService
from shared.pagination import PageQuery
from shared.serializers import validated
from shared.views import UserAPIView


class ChannelDetailView(UserAPIView):
    async def get(self, request, channel_id: UUID):
        detail = await ChannelService.get(channel_id, request.user.id)
        return Response(ChannelDetailResponse(detail).data)


class TeamChannelsView(UserAPIView):
    async def get(self, request, team_id: UUID):
        channels = await ChannelService.list_mine(team_id, request.user.id)
        return Response({"channels": MyChannelResponse(channels, many=True).data})

    async def post(self, request, team_id: UUID):
        data = validated(CreateChannelRequest, request.data)
        channel = await ChannelService.create(team_id, request.user.id, **data)
        return Response(ChannelResponse(channel).data, status=201)


class BrowseChannelsView(UserAPIView):
    async def get(self, request, team_id: UUID):
        params = validated(BrowseChannelsQuery, request.query_params)
        channels, next_cursor = await ChannelService.browse(team_id, request.user.id, **params)
        return Response(
            {
                "channels": BrowseChannelResponse(channels, many=True).data,
                "next_cursor": next_cursor,
            }
        )


class JoinChannelView(UserAPIView):
    async def post(self, request, channel_id: UUID):
        member = await ChannelService.join(channel_id, request.user.id)
        return Response(JoinChannelResponse(member).data)


class LeaveChannelView(UserAPIView):
    async def post(self, request, channel_id: UUID):
        await ChannelService.leave(channel_id, request.user.id)
        return Response(status=204)


class ChannelMembersView(UserAPIView):
    async def get(self, request, channel_id: UUID):
        params = validated(PageQuery, request.query_params)
        members, next_cursor = await ChannelService.list_members(
            channel_id, request.user.id, **params
        )
        return Response(
            {
                "members": ChannelMemberResponse(members, many=True).data,
                "next_cursor": next_cursor,
            }
        )
