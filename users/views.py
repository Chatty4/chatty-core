from rest_framework.response import Response

from shared.http import client_ip
from shared.serializers import validated
from shared.views import AsyncAPIView, UserAPIView
from users.serializers import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    MeResponse,
    RegisterRequest,
    TokenPairResponse,
    TokenRequest,
    UpdateMeRequest,
    UserResponse,
)
from users.services import UserService


class RegisterView(AsyncAPIView):
    authentication_classes = []

    async def post(self, request):
        data = validated(RegisterRequest, request.data)
        user = await UserService.register(**data, ip=client_ip(request))
        return Response(UserResponse(user).data, status=201)


class LoginView(AsyncAPIView):
    authentication_classes = []

    async def post(self, request):
        data = validated(LoginRequest, request.data)
        tokens, user = await UserService.login(**data, ip=client_ip(request))
        return Response(LoginResponse({"user": user, **tokens.model_dump()}).data)


class RefreshTokenView(AsyncAPIView):
    authentication_classes = []

    async def post(self, request):
        data = validated(TokenRequest, request.data)
        tokens = await UserService.refresh_token(**data)
        return Response(TokenPairResponse(tokens).data)


class LogoutView(UserAPIView):
    async def post(self, request):
        data = validated(TokenRequest, request.data)
        await UserService.logout(**data, user_id=request.user.id)
        return Response(status=204)


class MeView(UserAPIView):
    async def get(self, request):
        return Response(MeResponse(request.user).data)

    async def put(self, request):
        data = validated(UpdateMeRequest, request.data)
        user = await UserService.update_profile(request.user, **data)

        return Response(MeResponse(user).data)


class ChangePasswordView(UserAPIView):
    async def post(self, request):
        data = validated(ChangePasswordRequest, request.data, context={"user": request.user})
        await UserService.change_password(request.user, **data)

        return Response(status=204)
