from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework.fields import get_error_detail

from users.models import User


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


class UserResponse(serializers.ModelSerializer):
    avatar_file_id = serializers.UUIDField(source="avatar_id")

    class Meta:
        model = User
        fields = ["id", "email", "display_name", "avatar_file_id", "timezone"]


class LoginRequest(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)


class TokenPairResponse(serializers.Serializer):
    access_token = serializers.CharField()
    token_type = serializers.CharField()
    expires_in = serializers.IntegerField()
    refresh_token = serializers.CharField()
    refresh_expires_in = serializers.IntegerField()
