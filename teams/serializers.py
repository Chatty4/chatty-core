from uuid import UUID

from rest_framework import serializers

from shared.pagination import PageQuery
from teams.models import TeamMember

_MAX_AGE_CHOICES = {0, 1800, 3600, 21600, 43200, 86400, 604800}
_MAX_USES_CHOICES = {0, 1, 5, 10, 25, 50, 100}


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


class ChangeRoleRequest(serializers.Serializer):
    role = serializers.ChoiceField(choices=TeamMember.Role.choices)


class MemberRoleResponse(serializers.Serializer):
    user_id = serializers.UUIDField()
    team_id = serializers.UUIDField()
    role = serializers.CharField()


# --- INVITES ---
class CreateInviteRequest(serializers.Serializer):
    max_age = serializers.IntegerField(default=604800)
    max_uses = serializers.IntegerField(default=0)

    def validate_max_age(self, value: int) -> int:
        if value not in _MAX_AGE_CHOICES:
            raise serializers.ValidationError(
                "Must be one of: 0, 1800, 3600, 21600, 43200, 86400, 604800"
            )
        return value

    def validate_max_uses(self, value: int) -> int:
        if value not in _MAX_USES_CHOICES:
            raise serializers.ValidationError("Must be one of: 0, 1, 5, 10, 25, 50, 100")
        return value


class BaseInviteResponse(serializers.Serializer):
    id = serializers.UUIDField()
    code = serializers.CharField()
    url = serializers.CharField()
    created_by = serializers.UUIDField(allow_null=True)
    max_uses = serializers.IntegerField()
    uses = serializers.IntegerField()
    expires_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()


class InviteResponse(BaseInviteResponse):
    team_id = serializers.UUIDField()


class TeamPreviewResponse(serializers.Serializer):
    name = serializers.CharField()
    icon_url = serializers.URLField(allow_null=True)
    member_count = serializers.IntegerField()


class InviteLookupResponse(serializers.Serializer):
    code = serializers.CharField()
    valid = serializers.BooleanField()
    reason = serializers.CharField(allow_null=True)
    team = TeamPreviewResponse()
    expires_at = serializers.DateTimeField(allow_null=True)
