import uuid

from django.conf import settings
from django.db import models


class RefreshToken(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="refresh_tokens",
    )
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "authn_refresh_tokens"
        indexes = [models.Index(fields=["user_id"])]

    def __str__(self) -> str:
        return f"RefreshToken({self.user_id}, expires={self.expires_at})"
