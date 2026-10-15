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


class TeamMemberResponse(serializers.Serializer):
    user_id = serializers.UUIDField()
    display_name = serializers.CharField(source="user.display_name")
    avatar_file_id = serializers.UUIDField(source="user.avatar_id", allow_null=True)
    role = serializers.CharField()
    is_active = serializers.BooleanField(source="user.is_active")
    joined_at = serializers.DateTimeField()
