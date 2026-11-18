from datetime import datetime, timedelta
from uuid import UUID

from django.contrib.auth import get_user_model
from django.db.models import Exists, OuterRef, Q, QuerySet

from files.models import File
from teams.models import Team

UNSENT_FILE_HOURS = 24  # D-17: the web app must send a file within 24 h of uploading it
EXPIRED_UPLOAD_GRACE = timedelta(hours=1)  # a confirm that started just before expiry can finish


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

    @staticmethod
    def mark_deleted_sync(file_id: UUID, now: datetime) -> None:
        File.objects.filter(id=file_id, deleted_at__isnull=True).update(deleted_at=now)

    @staticmethod
    def mark_attached_sync(file_ids: list[UUID], now: datetime) -> None:
        File.objects.filter(id__in=file_ids).update(attached_at=now)

    @staticmethod
    def mark_detached_sync(file_ids: list[UUID], now: datetime) -> None:
        """Attachments not deleted yet: out of their message, and deleted. Others are skipped."""
        File.objects.filter(
            id__in=file_ids, purpose=File.Purpose.ATTACHMENT, deleted_at__isnull=True
        ).update(attached_at=None, deleted_at=now)

    @staticmethod
    def lock_sync(file_id: UUID) -> File | None:
        """The file, its row locked until the transaction ends. Deleting it and using it as an
        avatar or a team icon all lock it first, so they never overlap."""
        return File.objects.select_for_update(no_key=True).filter(id=file_id).first()

    @staticmethod
    def lock_many_sync(file_ids: list[UUID]) -> dict[UUID, File]:
        """The files that exist, by id, their rows locked until the transaction ends. Locked in id
        order, so two transactions that lock some of the same files can't deadlock."""
        files = File.objects.select_for_update(no_key=True).filter(id__in=file_ids).order_by("id")
        return {file.id: file for file in files}

    @staticmethod
    def deleted_sync(limit: int) -> list[File]:
        """Files marked deleted, oldest first: their objects are next to remove from MinIO."""
        return list(File.objects.filter(deleted_at__isnull=False).order_by("deleted_at")[:limit])

    @staticmethod
    def delete_rows_sync(file_ids: list[UUID]) -> int:
        """Rows only; call this after their MinIO objects are gone."""
        count, _ = File.objects.filter(id__in=file_ids, deleted_at__isnull=False).delete()
        return count

    @staticmethod
    def _unused_qs(now: datetime) -> QuerySet[File]:
        """Files nobody needs anymore (D-17): the one rule the cleanup job uses."""
        day_ago = now - timedelta(hours=UNSENT_FILE_HOURS)
        ready_and_old = Q(status=File.Status.READY, created_at__lt=day_ago)
        return File.objects.filter(deleted_at__isnull=True).filter(
            # upload started, never confirmed
            Q(status=File.Status.PENDING, upload_expires_at__lt=now - EXPIRED_UPLOAD_GRACE)
            # attachment never sent in a message
            | (ready_and_old & Q(purpose=File.Purpose.ATTACHMENT, attached_at__isnull=True))
            # avatar nobody has (replaced, or never set)
            | (
                ready_and_old
                & Q(purpose=File.Purpose.AVATAR)
                & ~Exists(get_user_model().objects.filter(avatar_id=OuterRef("id")))
            )
            # team icon no team has
            | (
                ready_and_old
                & Q(purpose=File.Purpose.TEAM_ICON)
                & ~Exists(Team.objects.filter(icon_id=OuterRef("id")))
            )
            # any file of a deleted team, even attached ones: the team is 404 everywhere
            | Q(team__deleted_at__isnull=False)
        )

    @staticmethod
    def unused_ids_sync(now: datetime, limit: int) -> list[UUID]:
        return list(FileRepository._unused_qs(now).values_list("id", flat=True)[:limit])

    @staticmethod
    def is_unused_sync(file_id: UUID, now: datetime) -> bool:
        """The same rule for one file. Called under its row lock, so the answer holds."""
        return FileRepository._unused_qs(now).filter(id=file_id).exists()
