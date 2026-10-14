import uuid

from django.conf import settings
from django.db import models

from teams.models import Team


class Channel(models.Model):
    class Kind(models.TextChoices):
        PUBLIC = "public"
        PRIVATE = "private"
        DM = "dm"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="channels")
    name = models.CharField(max_length=100, blank=True)  # blank for DMs
    kind = models.CharField(max_length=10, choices=Kind.choices)
    topic = models.TextField(blank=True, default="")
    is_default = models.BooleanField(default=False)
    dm_key = models.CharField(
        max_length=500, blank=True, default=""
    )  # sorted UUIDs joined with ":"
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "channels"
        constraints = [
            models.UniqueConstraint(
                fields=["team", "name"],
                condition=models.Q(kind__in=["public", "private"]),
                name="unique_channel_name_per_team",
            ),
            models.UniqueConstraint(
                fields=["team", "dm_key"],
                condition=models.Q(kind="dm"),
                name="unique_dm_key_per_team",
            ),
        ]

    def __str__(self) -> str:
        return self.name or f"DM ({self.dm_key})"


class ChannelMember(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner"
        MEMBER = "member"

    class NotifyLevel(models.TextChoices):
        ALL = "all"
        MENTIONS = "mentions"
        NONE = "none"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="channel_memberships",
    )
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.MEMBER)
    notify_level = models.CharField(max_length=10, choices=NotifyLevel.choices)
    muted = models.BooleanField(default=False)
    hidden = models.BooleanField(default=False)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "channel_members"
        unique_together = [("channel", "user")]
        indexes = [models.Index(fields=["user"])]

    def __str__(self) -> str:
        return f"{self.user} in {self.channel} ({self.role})"
