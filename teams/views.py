from rest_framework.response import Response

from shared.serializers import validated
from shared.views import UserAPIView
from teams.serializers import CreateTeamRequest, CreateTeamResponse
from teams.services import TeamService


class CreateTeamView(UserAPIView):
    async def post(self, request):
        data = validated(CreateTeamRequest, request.data)
        result = await TeamService.create(**data, user_id=request.user.id)
        return Response(CreateTeamResponse(result).data, status=201)
