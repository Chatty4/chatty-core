from uuid import UUID

from rest_framework.response import Response

from shared.serializers import validated
from shared.views import UserAPIView
from teams.serializers import (
    ChangeRoleRequest,
    CreateTeamRequest,
    CreateTeamResponse,
    MemberRoleResponse,
    TeamDetailResponse,
    TeamMemberResponse,
    TeamMembersQuery,
    TeamResponse,
    UpdateTeamRequest,
)
from teams.services import TeamService


class TeamsView(UserAPIView):
    async def post(self, request):
        data = validated(CreateTeamRequest, request.data)
        result = await TeamService.create(**data, user_id=request.user.id)
        return Response(CreateTeamResponse(result).data, status=201)

    async def get(self, request):
        teams = await TeamService.list_for_user(user_id=request.user.id)
        return Response({"teams": TeamResponse(teams, many=True).data})


class TeamDetailView(UserAPIView):
    async def get(self, request, team_id: UUID):
        result = await TeamService.get(team_id=team_id, user_id=request.user.id)
        return Response(TeamDetailResponse(result).data)

    async def put(self, request, team_id: UUID):
        data = validated(UpdateTeamRequest, request.data)
        result = await TeamService.update(**data, team_id=team_id, user_id=request.user.id)
        return Response(TeamDetailResponse(result).data)

    async def delete(self, request, team_id: UUID):
        await TeamService.delete(team_id=team_id, user_id=request.user.id)
        return Response(status=204)


class TeamMembersView(UserAPIView):
    async def get(self, request, team_id: UUID):
        params = validated(TeamMembersQuery, request.query_params)
        members, next_cursor = await TeamService.list_members(team_id, request.user.id, **params)
        return Response(
            {"members": TeamMemberResponse(members, many=True).data, "next_cursor": next_cursor}
        )


class TeamMemberDetailView(UserAPIView):
    async def put(self, request, team_id: UUID, user_id: UUID):
        data = validated(ChangeRoleRequest, request.data)
        member = await TeamService.change_role(team_id, request.user.id, user_id, data["role"])
        return Response(MemberRoleResponse(member).data)

    async def delete(self, request, team_id: UUID, user_id: UUID):
        await TeamService.remove_member(team_id, request.user.id, user_id)
        return Response(status=204)
