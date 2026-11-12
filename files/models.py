import uuid

from django.conf import settings
from django.db import models

from teams.models import Team


class File(models.Model):
    class Purpose(models.TextChoices):
        AVATAR = "avatar"
        TEAM_ICON = "team_icon"
        ATTACHMENT = "attachment"

    class Status(models.TextChoices):
        PENDING = "pending"  # upload URL given, not confirmed yet
        READY = "ready"  # checked by confirm, can be used

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="files"
    )
    owner_id: uuid.UUID
    # Empty for avatars; set for team icons and attachments
    team = models.ForeignKey(
        Team, on_delete=models.CASCADE, null=True, blank=True, related_name="files"
    )
    team_id: uuid.UUID | None
    purpose = models.CharField(max_length=20, choices=Purpose.choices)
    object_key = models.CharField(max_length=200, unique=True)
    filename = models.CharField(max_length=255)
    mime = models.CharField(max_length=255)
    size = models.PositiveBigIntegerField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    upload_expires_at = models.DateTimeField()
    attached_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "files"
        indexes = [
            models.Index(fields=["status", "created_at"], name="files_status_created_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(purpose="avatar", team__isnull=True)
                    | (~models.Q(purpose="avatar") & models.Q(team__isnull=False))
                ),
                name="file_team_matches_purpose",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.filename} ({self.purpose}, {self.status})"
