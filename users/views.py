from rest_framework.response import Response

from shared.serializers import validated
from shared.views import AsyncAPIView
from users.serializers import LoginRequest, RegisterRequest, TokenPairResponse, UserResponse
from users.services import UserService


class RegisterView(AsyncAPIView):
    async def post(self, request):
        data = validated(RegisterRequest, request.data)
        user = await UserService.register(**data, ip=request.META["REMOTE_ADDR"])
        return Response(UserResponse(user).data, status=201)


class LoginView(AsyncAPIView):
    async def post(self, request):
        data = validated(LoginRequest, request.data)
        tokens = await UserService.login(**data, ip=request.META["REMOTE_ADDR"])
        return Response(TokenPairResponse(tokens).data)
