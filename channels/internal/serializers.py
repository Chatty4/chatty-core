from rest_framework import serializers

from channels.schemas import InternalChannel


class InternalChannelMemberResponse(serializers.Serializer):
    user_id = serializers.UUIDField()
    role = serializers.CharField()
    notify_level = serializers.CharField()
    muted = serializers.BooleanField()


class InternalChannelResponse(serializers.Serializer):
    channel_id = serializers.UUIDField(source="channel.id")
    team_id = serializers.UUIDField(source="channel.team_id")
    kind = serializers.CharField(source="channel.kind")
    archived = serializers.SerializerMethodField()
    team_deleted = serializers.SerializerMethodField()
    members = InternalChannelMemberResponse(many=True)

    def get_archived(self, item: InternalChannel) -> bool:
        return item.channel.archived_at is not None

    def get_team_deleted(self, item: InternalChannel) -> bool:
        return item.channel.team.deleted_at is not None  # team loaded by select_related
