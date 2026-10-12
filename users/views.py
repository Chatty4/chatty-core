from rest_framework.response import Response

from shared.serializers import validated
from shared.views import AsyncAPIView, UserAPIView
from users.serializers import (
    LoginRequest,
    LogoutRequest,
    MeResponse,
    RegisterRequest,
    TokenPairResponse,
    UpdateMeRequest,
    UserResponse,
)
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


class LogoutView(UserAPIView):
    async def post(self, request):
        data = validated(LogoutRequest, request.data)
        await UserService.logout(**data)
        return Response(status=204)


class MeView(UserAPIView):
    async def get(self, request):
        return Response(MeResponse(request.user).data)

    async def put(self, request):
        data = validated(UpdateMeRequest, request.data)
        user = await UserService.update_profile(request.user, **data)

        return Response(MeResponse(user).data)
