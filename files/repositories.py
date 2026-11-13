from datetime import datetime
from uuid import UUID

from django.contrib.auth import get_user_model
from django.db.models import QuerySet

from files.models import File


class FileRepository:
    @staticmethod
    async def get(file_id: UUID) -> File | None:
        return await File.objects.filter(id=file_id).afirst()

    @staticmethod
    def count_pending_sync(owner_id: UUID, now: datetime) -> int:
        """Open uploads of the owner (not confirmed, not expired, not deleted). Locks the owner's
        user row until the transaction ends, so two parallel uploads can't both pass the cap."""
        # no_key: other inserts that reference this user (logins, joins) don't wait
        get_user_model().objects.select_for_update(no_key=True).get(id=owner_id)
        return FileRepository._pending_qs(owner_id, now).count()

    @staticmethod
    def first_pending_expiry_sync(owner_id: UUID, now: datetime) -> datetime | None:
        """When the owner's oldest open upload expires: the Retry-After of the pending cap."""
        return (
            FileRepository._pending_qs(owner_id, now)
            .order_by("upload_expires_at")
            .values_list("upload_expires_at", flat=True)
            .first()
        )

    @staticmethod
    def _pending_qs(owner_id: UUID, now: datetime) -> QuerySet[File]:
        return File.objects.filter(
            owner_id=owner_id,
            status=File.Status.PENDING,
            upload_expires_at__gt=now,
            deleted_at__isnull=True,
        )

    @staticmethod
    def create_sync(
        file_id: UUID,
        owner_id: UUID,
        team_id: UUID | None,
        purpose: str,
        object_key: str,
        filename: str,
        mime: str,
        size: int,
        upload_expires_at: datetime,
    ) -> File:
        """A pending file. The service picks file_id first, because object_key contains it."""
        return File.objects.create(
            id=file_id,
            owner_id=owner_id,
            team_id=team_id,
            purpose=purpose,
            object_key=object_key,
            filename=filename,
            mime=mime,
            size=size,
            upload_expires_at=upload_expires_at,
        )

    @staticmethod
    async def mark_ready(file_id: UUID) -> bool:
        """pending -> ready. False if the file is no longer pending or was deleted meanwhile."""
        updated = await File.objects.filter(
            id=file_id, status=File.Status.PENDING, deleted_at__isnull=True
        ).aupdate(status=File.Status.READY)
        return updated == 1

    @staticmethod
    async def mark_deleted(file_id: UUID, now: datetime) -> None:
        """The file can't be used anymore, the cleanup job removes the row."""
        await File.objects.filter(id=file_id, deleted_at__isnull=True).aupdate(deleted_at=now)
