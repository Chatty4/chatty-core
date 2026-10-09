from rest_framework.response import Response

from shared.serializers import validated
from shared.views import AsyncAPIView
from users.serializers import RegisterRequest, UserResponse
from users.services import UserService


class RegisterView(AsyncAPIView):
    async def post(self, request):
        data = validated(RegisterRequest, request.data)
        user = await UserService.register(**data, ip=request.META["REMOTE_ADDR"])
        return Response(UserResponse(user).data, status=201)
