import unicodedata

from rest_framework import serializers

from files.models import File

# Bidirectional overrides make "invoice\u202efdp.exe" display as "invoiceexe.pdf".
_BIDI_CONTROLS = set("\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")


def _clean_filename(name: str) -> str:
    """The name without path separators, control characters and bidirectional overrides."""
    kept = (
        c
        for c in name
        if c not in "/\\" and c not in _BIDI_CONTROLS and unicodedata.category(c) != "Cc"
    )
    return "".join(kept).strip()


class CreateFileRequest(serializers.Serializer):
    purpose = serializers.ChoiceField(choices=File.Purpose.choices)
    team_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    filename = serializers.CharField(min_length=1, max_length=255, trim_whitespace=False)
    mime = serializers.CharField(max_length=255)
    size = serializers.IntegerField(min_value=1)

    def validate_filename(self, value: str) -> str:
        cleaned = _clean_filename(value)
        if not cleaned:
            raise serializers.ValidationError("only unsafe characters", code="invalid")
        return cleaned

    def validate(self, attrs: dict) -> dict:
        # avatars belong to the user, team icons and attachments to a team
        if attrs["purpose"] == File.Purpose.AVATAR and attrs["team_id"] is not None:
            raise serializers.ValidationError(
                {"team_id": "must be null for an avatar"}, code="invalid"
            )
        if attrs["purpose"] != File.Purpose.AVATAR and attrs["team_id"] is None:
            raise serializers.ValidationError({"team_id": "required"}, code="required")
        return attrs


class UploadResponse(serializers.Serializer):
    file_id = serializers.UUIDField()
    upload_url = serializers.CharField()
    upload_method = serializers.CharField()
    upload_headers = serializers.DictField(child=serializers.CharField())
    expires_at = serializers.DateTimeField()
