from uuid import UUID

from rest_framework.response import Response

from channels.serializers import (
    AddChannelMemberRequest,
    BrowseChannelResponse,
    BrowseChannelsQuery,
    ChannelDetailResponse,
    ChannelMemberResponse,
    ChannelResponse,
    CreateChannelRequest,
    DMResponse,
    JoinChannelResponse,
    MyChannelResponse,
    OpenDMRequest,
    UpdateChannelRequest,
    UpdateMySettingsRequest,
)
from channels.services import ChannelService
from shared.pagination import PageQuery
from shared.serializers import validated
from shared.views import AsyncAPIView


class ChannelDetailView(AsyncAPIView):
    async def get(self, request, channel_id: UUID):
        detail = await ChannelService.get(channel_id, request.user.id)
        return Response(ChannelDetailResponse(detail).data)

    async def put(self, request, channel_id: UUID):
        data = validated(UpdateChannelRequest, request.data)
        detail = await ChannelService.update(channel_id, request.user.id, **data)
        return Response(ChannelDetailResponse(detail).data)


class TeamChannelsView(AsyncAPIView):
    async def get(self, request, team_id: UUID):
        channels = await ChannelService.list_mine(team_id, request.user.id)
        return Response({"channels": MyChannelResponse(channels, many=True).data})

    async def post(self, request, team_id: UUID):
        data = validated(CreateChannelRequest, request.data)
        channel = await ChannelService.create(team_id, request.user.id, **data)
        return Response(ChannelResponse(channel).data, status=201)


class BrowseChannelsView(AsyncAPIView):
    async def get(self, request, team_id: UUID):
        params = validated(BrowseChannelsQuery, request.query_params)
        channels, next_cursor = await ChannelService.browse(team_id, request.user.id, **params)
        return Response(
            {
                "channels": BrowseChannelResponse(channels, many=True).data,
                "next_cursor": next_cursor,
            }
        )


class JoinChannelView(AsyncAPIView):
    async def post(self, request, channel_id: UUID):
        member = await ChannelService.join(channel_id, request.user.id)
        return Response(JoinChannelResponse(member).data)


class LeaveChannelView(AsyncAPIView):
    async def post(self, request, channel_id: UUID):
        await ChannelService.leave(channel_id, request.user.id)
        return Response(status=204)


class ChannelMembersView(AsyncAPIView):
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

    async def post(self, request, channel_id: UUID):
        data = validated(AddChannelMemberRequest, request.data)
        added, already = await ChannelService.add_members(channel_id, request.user.id, **data)
        return Response({"added": added, "already_members": already})


class ChannelMemberDetailView(AsyncAPIView):
    async def delete(self, request, channel_id: UUID, user_id: UUID):
        await ChannelService.remove_member(channel_id, request.user.id, user_id)
        return Response(status=204)


class ArchiveChannelView(AsyncAPIView):
    async def post(self, request, channel_id: UUID):
        detail = await ChannelService.archive(channel_id, request.user.id)
        return Response(ChannelDetailResponse(detail).data)


class MyChannelSettingsView(UserAPIView):
    async def put(self, request, channel_id: UUID):
        data = validated(UpdateMySettingsRequest, request.data)
        member = await ChannelService.update_my_settings(channel_id, request.user.id, **data)
        return Response(JoinChannelResponse(member).data)


class TeamDMsView(UserAPIView):
    async def post(self, request, team_id: UUID):
        data = validated(OpenDMRequest, request.data)
        result = await ChannelService.open_dm(team_id, request.user.id, data["user_ids"])
        return Response(DMResponse(result).data, status=201 if result.created else 200)
