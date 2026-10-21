from uuid import UUID

from rest_framework.response import Response

from shared.views import InternalAPIView
from users.internal.serializers import MembershipsResponse
from users.services import UserService


class MembershipsView(InternalAPIView):
    async def get(self, request, user_id: UUID):
        memberships = await UserService.get_memberships(user_id)
        return Response(MembershipsResponse(memberships).data)
