from rest_framework import serializers

MAX_FILES = 10


class AttachRequest(serializers.Serializer):
    user_id = serializers.UUIDField()
    channel_id = serializers.UUIDField()
    file_ids = serializers.ListField(
        child=serializers.UUIDField(), min_length=1, max_length=MAX_FILES
    )

    def validate_file_ids(self, value: list) -> list:
        if len(set(value)) != len(value):
            raise serializers.ValidationError("A file is in the list twice", code="invalid")
        return value


class AttachmentResponse(serializers.Serializer):
    file_id = serializers.UUIDField(source="id")
    object_key = serializers.CharField()
    filename = serializers.CharField()
    mime = serializers.CharField()
    size = serializers.IntegerField()
    attached_at = serializers.DateTimeField()


class AttachResponse(serializers.Serializer):
    attachments = AttachmentResponse(many=True)
