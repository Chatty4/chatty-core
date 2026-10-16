from rest_framework import serializers

from channels.models import Channel
from channels.schemas import ChannelDetail, MyChannel
from shared.pagination import PageQuery


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


class MySettingsResponse(serializers.Serializer):
    role = serializers.CharField()
    notify_level = serializers.CharField()
    muted = serializers.BooleanField()
    hidden = serializers.BooleanField()


class MyChannelResponse(serializers.Serializer):
    id = serializers.UUIDField(source="channel.id")
    kind = serializers.CharField(source="channel.kind")
    name = serializers.SerializerMethodField()
    topic = serializers.SerializerMethodField()
    is_default = serializers.BooleanField(source="channel.is_default")
    archived = serializers.SerializerMethodField()
    dm_member_ids = serializers.ListField(child=serializers.UUIDField(), allow_null=True)
    my = MySettingsResponse()

    def get_name(self, item: MyChannel) -> str | None:
        return None if item.channel.kind == Channel.Kind.DM else item.channel.name

    def get_topic(self, item: MyChannel) -> str | None:
        return None if item.channel.kind == Channel.Kind.DM else item.channel.topic

    def get_archived(self, item: MyChannel) -> bool:
        return item.channel.archived_at is not None


class BrowseChannelsQuery(PageQuery):
    q = serializers.CharField(required=False, allow_blank=True)


class BrowseChannelResponse(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    topic = serializers.CharField()
    member_count = serializers.IntegerField()
    archived = serializers.SerializerMethodField()

    def get_archived(self, channel: Channel) -> bool:
        return channel.archived_at is not None


class ChannelDetailResponse(serializers.Serializer):
    """ChannelResponse plus member_count and my (null when I haven't joined)."""

    def to_representation(self, detail: ChannelDetail) -> dict:
        return {
            **ChannelResponse(detail.channel).data,
            "member_count": detail.member_count,
            "my": MySettingsResponse(detail.my).data if detail.my else None,
        }


class JoinChannelResponse(MySettingsResponse):
    channel_id = serializers.UUIDField()


class ChannelMemberResponse(serializers.Serializer):
    user_id = serializers.UUIDField()
    role = serializers.CharField()
    joined_at = serializers.DateTimeField()
