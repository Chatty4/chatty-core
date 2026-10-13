from zoneinfo import available_timezones

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework.fields import get_error_detail

from users.models import User

_VALID_TIMEZONES = available_timezones()


class RegisterRequest(serializers.Serializer):
    email = serializers.EmailField()
    display_name = serializers.CharField(max_length=60)
    password = serializers.CharField(write_only=True)

    def validate(self, attrs: dict) -> dict:

        user = User(email=attrs["email"], display_name=attrs["display_name"])

        try:
            validate_password(attrs["password"], user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": get_error_detail(exc)})

        return attrs

    def validate_email(self, value: str) -> str:
        return User.objects.normalize_email(value).lower()


class UserResponse(serializers.ModelSerializer):
    avatar_file_id = serializers.UUIDField(source="avatar_id")

    class Meta:
        model = User
        fields = ["id", "email", "display_name", "avatar_file_id", "timezone"]


class LoginRequest(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate_email(self, value: str) -> str:
        return User.objects.normalize_email(value).lower()


class TokenPairResponse(serializers.Serializer):
    access_token = serializers.CharField()
    token_type = serializers.CharField()
    expires_in = serializers.IntegerField()
    refresh_token = serializers.CharField()
    refresh_expires_in = serializers.IntegerField()


class LoginResponse(TokenPairResponse):
    user = UserResponse()


class TokenRequest(serializers.Serializer):
    refresh_token = serializers.CharField()


class UpdateMeRequest(serializers.Serializer):
    display_name = serializers.CharField(max_length=60)
    timezone = serializers.CharField()
    # shortcut: any UUID is accepted until files app exists
    avatar_file_id = serializers.UUIDField(allow_null=True)

    def validate_timezone(self, value: str) -> str:
        if value not in _VALID_TIMEZONES:
            raise serializers.ValidationError("unknown timezone", code="invalid")
        return value


class MeResponse(UserResponse):
    teams = serializers.SerializerMethodField()

    class Meta(UserResponse.Meta):
        fields = [*UserResponse.Meta.fields, "date_joined", "teams"]

    def get_teams(self, user: User) -> list:
        return []  # shortcut: no teams app yet, fill in when the Team model lands.


class ChangePasswordRequest(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)
    refresh_token = serializers.CharField()

    def validate(self, attrs: dict) -> dict:
        if attrs["new_password"] == attrs["old_password"]:
            raise serializers.ValidationError(
                {"new_password": "must differ from the old password"}, code="invalid"
            )
        try:
            validate_password(attrs["new_password"], self.context["user"])
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"new_password": get_error_detail(exc)})
        return attrs
