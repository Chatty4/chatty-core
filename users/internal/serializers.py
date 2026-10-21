from rest_framework import serializers

from channels.models import ChannelMember
from channels.serializers import MySettingsResponse


class TeamMembershipResponse(serializers.Serializer):
    team_id = serializers.UUIDField()
    role = serializers.CharField()
    public_channel_ids = serializers.ListField(child=serializers.UUIDField())


class ChannelMembershipResponse(MySettingsResponse):
    """MySettingsResponse (role, notify_level, muted, hidden) plus the channel."""

    channel_id = serializers.UUIDField()
    team_id = serializers.UUIDField(source="channel.team_id")
    kind = serializers.CharField(source="channel.kind")
    archived = serializers.SerializerMethodField()

    def get_archived(self, member: ChannelMember) -> bool:
        return member.channel.archived_at is not None


class MembershipsResponse(serializers.Serializer):
    user_id = serializers.UUIDField()
    is_active = serializers.BooleanField()
    teams = TeamMembershipResponse(many=True)
    channels = ChannelMembershipResponse(many=True)
