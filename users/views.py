from rest_framework.response import Response

from shared.http import client_ip
from shared.serializers import validated
from shared.views import AsyncAPIView
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
    permission_classes = []

    async def post(self, request):
        data = validated(RegisterRequest, request.data)
        user = await UserService.register(**data, ip=client_ip(request))
        return Response(UserResponse(user).data, status=201)


class LoginView(AsyncAPIView):
    authentication_classes = []
    permission_classes = []

    async def post(self, request):
        data = validated(LoginRequest, request.data)
        tokens, user = await UserService.login(**data, ip=client_ip(request))
        return Response(LoginResponse({"user": user, **tokens.model_dump()}).data)


class RefreshTokenView(AsyncAPIView):
    authentication_classes = []
    permission_classes = []

    async def post(self, request):
        data = validated(TokenRequest, request.data)
        tokens = await UserService.refresh_token(**data)
        return Response(TokenPairResponse(tokens).data)


class LogoutView(AsyncAPIView):
    async def post(self, request):
        data = validated(TokenRequest, request.data)
        await UserService.logout(**data, user_id=request.user.id)
        return Response(status=204)


class MeView(AsyncAPIView):
    async def get(self, request):
        me = await UserService.get_me(request.user)
        return Response(MeResponse(me.user, context={"teams": me.teams}).data)

    async def put(self, request):
        data = validated(UpdateMeRequest, request.data)
        me = await UserService.update_profile(request.user, **data)

        return Response(MeResponse(me.user, context={"teams": me.teams}).data)


class ChangePasswordView(AsyncAPIView):
    async def post(self, request):
        data = validated(ChangePasswordRequest, request.data, context={"user": request.user})
        await UserService.change_password(request.user, **data)

        return Response(status=204)
