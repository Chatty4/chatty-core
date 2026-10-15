from uuid import UUID

from rest_framework import serializers

from shared.pagination import PageQuery


class CreateTeamRequest(serializers.Serializer):
    name = serializers.CharField(min_length=1, max_length=80)


class TeamResponse(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    icon_file_id = serializers.UUIDField(allow_null=True)
    role = serializers.CharField()
    member_count = serializers.IntegerField()
    created_at = serializers.DateTimeField()


class CreateTeamResponse(TeamResponse):
    general_channel_id = serializers.UUIDField()


class TeamMembersQuery(PageQuery):
    q = serializers.CharField(required=False, allow_blank=True)
    user_ids = serializers.CharField(required=False)

    def validate_user_ids(self, value: str) -> list[UUID]:
        ids = value.split(",")
        if len(ids) > 100:
            raise serializers.ValidationError("At most 100 user ids", code="too_many")
        return [serializers.UUIDField().to_internal_value(i) for i in ids]

    def validate(self, data: dict) -> dict:
        if "user_ids" in data and "cursor" in data:
            raise serializers.ValidationError(
                {"user_ids": "Can't be used with cursor"}, code="not_with_cursor"
            )
        return data


class TeamMemberResponse(serializers.Serializer):
    user_id = serializers.UUIDField()
    display_name = serializers.CharField(source="user.display_name")
    avatar_file_id = serializers.UUIDField(source="user.avatar_id", allow_null=True)
    role = serializers.CharField()
    is_active = serializers.BooleanField(source="user.is_active")
    joined_at = serializers.DateTimeField()
