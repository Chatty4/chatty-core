from rest_framework import serializers


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


class TeamDetailResponse(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    icon_file_id = serializers.UUIDField(allow_null=True)
    my_role = serializers.CharField()
    member_count = serializers.IntegerField()
    created_by = serializers.UUIDField(allow_null=True)
    created_at = serializers.DateTimeField()


class UpdateTeamRequest(serializers.Serializer):
    name = serializers.CharField(min_length=1, max_length=80)
    icon_file_id = serializers.UUIDField(allow_null=True)
