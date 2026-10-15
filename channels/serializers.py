from rest_framework import serializers

from channels.models import Channel


class CreateChannelRequest(serializers.Serializer):
    name = serializers.RegexField(r"^[a-z0-9_-]+$", max_length=80)
    kind = serializers.ChoiceField(choices=[Channel.Kind.PUBLIC, Channel.Kind.PRIVATE])
    topic = serializers.CharField(required=False, allow_blank=True, max_length=250, default="")


class ChannelResponse(serializers.Serializer):
    id = serializers.UUIDField()
    team_id = serializers.UUIDField()
    kind = serializers.CharField()
    name = serializers.CharField()
    topic = serializers.CharField()
    is_default = serializers.BooleanField()
    archived = serializers.SerializerMethodField()
    created_by = serializers.UUIDField(source="created_by_id", allow_null=True)
    created_at = serializers.DateTimeField()

    def get_archived(self, channel: Channel) -> bool:
        return channel.archived_at is not None
